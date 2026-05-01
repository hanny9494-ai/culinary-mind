import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, existsSync, readFileSync, rmSync, mkdirSync, readdirSync } from 'node:fs';
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
  fn: (ctx: { root: string; handleResult: (filePath: string) => void }) => void,
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
    fn({ root, handleResult });
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

test('orphan: result without task_id is archived not deleted', () => {
  withFixture(({ root, handleResult }) => {
    const resultPath = writeResult(root, 'result_architect_orphan.json', {
      from: 'architect',
      status: 'done',
      summary: 'x',
    });

    handleResult(resultPath);

    assert.equal(existsSync(resultPath), false);
    assert.equal(existsSync(join(root, '.ce-hub', 'results', '_orphan_no_task_id', 'result_architect_orphan.json')), true);
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
    assert.equal(existsSync(join(root, '.ce-hub', 'results', '_processed', 'result_architect_ref_dispatch.json')), true);
    assert.equal(existsSync(join(root, '.ce-hub', 'results', '_orphan_no_task_id', 'result_architect_ref_dispatch.json')), false);
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
    assert.equal(existsSync(join(root, '.ce-hub', 'results', '_processed', 'result_architect_processed.json')), true);
  }, makeStore({ id: 'task_ok', from_agent: 'cc-lead' }));
});
