import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mkdtempSync,
  writeFileSync,
  existsSync,
  readFileSync,
  rmSync,
  mkdirSync,
  readdirSync,
  renameSync as fsRenameSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { FileWatcher } from '../src/file-watcher.js';
import type { StateStore } from '../src/state-store.js';
import type { TmuxManager } from '../src/tmux-manager.js';

type HandleResult = { handleResult(filePath: string): void };

function makeTmux(): TmuxManager {
  return {
    isAlive: () => false,
    sendMessage: () => {},
  } as unknown as TmuxManager;
}

function makeStore(task: Record<string, unknown> | null = null): StateStore {
  return {
    getTask: () => task,
    updateTask: () => task,
    createEvent: () => ({}),
  } as unknown as StateStore;
}

function withFixture(
  fn: (ctx: { root: string; handleResult: (filePath: string) => void; watcher: FileWatcher }) => void,
  store: StateStore = makeStore()
): void {
  const previousCwd = process.env.CE_HUB_CWD;
  const root = mkdtempSync(join(tmpdir(), 'cehub-watcher-'));
  process.env.CE_HUB_CWD = root;
  mkdirSync(join(root, '.ce-hub', 'results'), { recursive: true });

  const watcher = new FileWatcher(makeTmux(), store);
  const handleResult = (filePath: string) => {
    (watcher as unknown as HandleResult).handleResult(filePath);
  };

  try {
    fn({ root, handleResult, watcher });
  } finally {
    if (previousCwd === undefined) {
      delete process.env.CE_HUB_CWD;
    } else {
      process.env.CE_HUB_CWD = previousCwd;
    }
    rmSync(root, { recursive: true, force: true });
  }
}

function writeResult(root: string, filename: string, data: Record<string, unknown>): string {
  const resultPath = join(root, '.ce-hub', 'results', filename);
  writeFileSync(resultPath, JSON.stringify(data, null, 2));
  return resultPath;
}

function listJsonFiles(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.endsWith('.json')).sort();
}

test('orphan: result without task_id is archived not deleted', () => {
  withFixture(({ root, handleResult }) => {
    const resultPath = writeResult(root, 'result_architect_orphan.json', {
      from: 'architect',
      status: 'done',
      summary: 'x',
    });

    handleResult(resultPath);

    assert.equal(existsSync(resultPath), false);
    const orphanDir = join(root, '.ce-hub', 'results', '_orphan_no_task_id');
    const files = listJsonFiles(orphanDir);
    assert.equal(files.length, 1);
    // Q2 — archived filename has unique suffix; basename stem matches source.
    assert.match(files[0], /^result_architect_orphan__\d+_\d+_[a-z0-9]+\.json$/);
  });
});

test('fallback: ref_dispatch is honored when task_id missing', () => {
  withFixture(({ root, handleResult }) => {
    const resultPath = writeResult(root, 'result_architect_ref_dispatch.json', {
      from: 'architect',
      ref_dispatch: 'task_abc',
      status: 'done',
      summary: 'x',
    });

    handleResult(resultPath);

    assert.equal(existsSync(resultPath), false);
    const processedDir = join(root, '.ce-hub', 'results', '_processed');
    const orphanDir = join(root, '.ce-hub', 'results', '_orphan_no_task_id');
    const undeliverableDir = join(root, '.ce-hub', 'inbox', '_undeliverable');
    // ref_dispatch fallback resolves to taskId, but the task isn't in DB AND
    // there's no data.to — so the result is undeliverable, not _processed.
    assert.equal(listJsonFiles(processedDir).length, 0);
    assert.equal(listJsonFiles(orphanDir).length, 0);
    const undeliverableFiles = listJsonFiles(undeliverableDir);
    assert.equal(undeliverableFiles.length, 1);
    assert.match(undeliverableFiles[0], /^result_architect_ref_dispatch__/);
  });
});

test('fallback: data.to forwards to inbox when task not in DB', () => {
  withFixture(({ root, handleResult }) => {
    const resultPath = writeResult(root, 'result_architect_to_fallback.json', {
      from: 'architect',
      task_id: 'unknown_xxx',
      to: 'cc-lead',
      status: 'done',
      summary: 'x',
    });

    handleResult(resultPath);

    const inboxDir = join(root, '.ce-hub', 'inbox', 'cc-lead');
    const resultFiles = readdirSync(inboxDir).filter((file) => file.startsWith('result_architect_') && file.endsWith('.json'));
    assert.equal(resultFiles.length, 1);

    const forwarded = JSON.parse(readFileSync(join(inboxDir, resultFiles[0]), 'utf-8'));
    assert.equal(forwarded.task_id, 'unknown_xxx');

    // And the source result lands in _processed/ (originAgent resolved via data.to).
    const processedFiles = listJsonFiles(join(root, '.ce-hub', 'results', '_processed'));
    assert.equal(processedFiles.length, 1);
  }, makeStore(null));
});

test('raw archive runs even for orphan', () => {
  withFixture(({ root, handleResult }) => {
    const resultPath = writeResult(root, 'result_architect_raw_orphan.json', {
      from: 'architect',
      status: 'done',
      summary: 'raw evidence',
    });

    handleResult(resultPath);

    const rawPath = join(root, '.ce-hub', 'raw', 'results.jsonl');
    assert.equal(existsSync(rawPath), true);

    const lines = readFileSync(rawPath, 'utf-8').trim().split('\n');
    assert.equal(lines.length, 1);

    const archived = JSON.parse(lines[0]);
    assert.equal(archived.from, 'architect');
    assert.equal(archived.status, 'done');
    assert.equal(archived.summary, 'raw evidence');
  });
});

test('processed: success path moves to _processed', () => {
  withFixture(({ root, handleResult }) => {
    const resultPath = writeResult(root, 'result_architect_processed.json', {
      from: 'architect',
      task_id: 'task_ok',
      status: 'done',
      summary: 'x',
    });

    handleResult(resultPath);

    assert.equal(existsSync(resultPath), false);
    const processedDir = join(root, '.ce-hub', 'results', '_processed');
    const files = listJsonFiles(processedDir);
    assert.equal(files.length, 1);
    assert.match(files[0], /^result_architect_processed__\d+_\d+_[a-z0-9]+\.json$/);
  }, makeStore({ id: 'task_ok', from_agent: 'cc-lead' }));
});

// ── New tests for PR #22 revisions ────────────────────────────────────────────

test('Q2 — duplicate basename does not overwrite existing orphan', () => {
  withFixture(({ root, handleResult }) => {
    // Two orphan results with the same source basename, one after the other.
    const sameName = 'collide.json';

    const first = writeResult(root, sameName, { from: 'a', status: 'done', summary: 'first' });
    handleResult(first);

    const second = writeResult(root, sameName, { from: 'b', status: 'done', summary: 'second' });
    handleResult(second);

    const orphanDir = join(root, '.ce-hub', 'results', '_orphan_no_task_id');
    const files = listJsonFiles(orphanDir);
    assert.equal(files.length, 2, 'both orphan archives must be retained');

    // Both unique-suffixed.
    for (const f of files) {
      assert.match(f, /^collide__\d+_\d+_[a-z0-9]+\.json$/);
    }

    const contents = files.map((f) => JSON.parse(readFileSync(join(orphanDir, f), 'utf-8')));
    const summaries = contents.map((c) => c.summary).sort();
    assert.deepEqual(summaries, ['first', 'second']);
  });
});

test('Q3+Q7 — 5 EBUSY rename failures result in quarantine + idempotent appendRaw', () => {
  withFixture(({ root, handleResult, watcher }) => {
    // Mock the rename wrapper: throw EBUSY for archives targeting the orphan
    // directory; allow renames into _archive_failed/ to succeed via real fs.
    let orphanAttempts = 0;
    (watcher as unknown as { safeRenameSync: (s: string, d: string) => void }).safeRenameSync =
      function (src: string, dst: string) {
        if (dst.includes('_orphan_no_task_id')) {
          orphanAttempts++;
          const e = new Error('Resource busy') as Error & { code: string };
          e.code = 'EBUSY';
          throw e;
        }
        fsRenameSync(src, dst);
      };

    const resultPath = writeResult(root, 'busy.json', {
      from: 'architect',
      status: 'done',
      summary: 'will fail to archive',
    });

    // Drive 5 invocations — first 4 transient failures, 5th forces quarantine.
    for (let i = 0; i < FileWatcher_MAX_RENAME_RETRIES; i++) {
      handleResult(resultPath);
    }

    assert.equal(orphanAttempts, FileWatcher_MAX_RENAME_RETRIES, '5 attempts hit the orphan dir');
    assert.equal(existsSync(resultPath), false, 'source must be removed after quarantine');

    const failedDir = join(root, '.ce-hub', 'results', '_archive_failed');
    const failedFiles = listJsonFiles(failedDir);
    assert.equal(failedFiles.length, 1, 'file should be quarantined to _archive_failed/');

    // Marker line in raw/archive_failures.jsonl
    const failuresLog = join(root, '.ce-hub', 'raw', 'archive_failures.jsonl');
    assert.equal(existsSync(failuresLog), true);
    const failureLines = readFileSync(failuresLog, 'utf-8').trim().split('\n');
    assert.equal(failureLines.length, 1);
    const marker = JSON.parse(failureLines[0]);
    assert.equal(marker.attempts, FileWatcher_MAX_RENAME_RETRIES);
    assert.equal(marker.error, 'Resource busy');

    // Idempotency: appendRaw('results.jsonl') runs only once across 5 invocations.
    const resultsLog = join(root, '.ce-hub', 'raw', 'results.jsonl');
    const resultsLines = readFileSync(resultsLog, 'utf-8').trim().split('\n');
    assert.equal(resultsLines.length, 1, 'appendRaw must be idempotent across retries');
  });
});

test('L2 — undeliverable: task_id present, no DB row, no data.to → _undeliverable/', () => {
  withFixture(({ root, handleResult }) => {
    const resultPath = writeResult(root, 'result_orphan_routing.json', {
      from: 'architect',
      task_id: 'unknown_yyy',
      status: 'done',
      summary: 'no recipient',
      // intentionally no `to`
    });

    handleResult(resultPath);

    assert.equal(existsSync(resultPath), false);
    const undeliverableDir = join(root, '.ce-hub', 'inbox', '_undeliverable');
    const files = listJsonFiles(undeliverableDir);
    assert.equal(files.length, 1, 'undeliverable result must land in inbox/_undeliverable/');
    assert.match(files[0], /^result_orphan_routing__/);

    // Should NOT be in _processed/
    const processedDir = join(root, '.ce-hub', 'results', '_processed');
    assert.equal(listJsonFiles(processedDir).length, 0);

    // raw/results.jsonl should have the standard line PLUS a marker line with type=undeliverable.
    const rawPath = join(root, '.ce-hub', 'raw', 'results.jsonl');
    assert.equal(existsSync(rawPath), true);
    const lines = readFileSync(rawPath, 'utf-8').trim().split('\n');
    assert.equal(lines.length, 2);
    const parsed = lines.map((l) => JSON.parse(l));
    assert.ok(parsed.some((p) => p.type === 'undeliverable'), 'undeliverable marker line missing');
  }, makeStore(null));
});

// Mirror MAX_RENAME_RETRIES from FileWatcher (kept private). Update if changed.
const FileWatcher_MAX_RENAME_RETRIES = 5;
