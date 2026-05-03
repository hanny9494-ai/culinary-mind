import test from 'node:test';
import assert from 'node:assert/strict';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { StateStore } from '../src/state-store.js';
import { SessionManager } from '../src/session-manager.js';
import { FileWatcher } from '../src/file-watcher.js';
import { atomicWriteJson, sanitizeSummaryLine } from '../src/quarantine.js';
import type { TmuxManager } from '../src/tmux-manager.js';

type WatcherPrivate = {
  handleAck(filePath: string): void;
  handleDispatch(filePath: string): void;
  pendingResults: Map<string, { agent: string; dispatchedAt: number; nudgeCount: number }>;
};

function setD68Flags(enabled: boolean): Record<string, string | undefined> {
  const keys = ['CE_HUB_D68_SESSIONS', 'CE_HUB_D68_QUARANTINE', 'CE_HUB_D68_ACKS'];
  const previous: Record<string, string | undefined> = {};
  for (const key of keys) {
    previous[key] = process.env[key];
    if (enabled) process.env[key] = '1';
    else delete process.env[key];
  }
  return previous;
}

function restoreEnv(previous: Record<string, string | undefined>): void {
  for (const [key, value] of Object.entries(previous)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
}

function makeTmux(sent: string[] = []): TmuxManager {
  return {
    startAgent: () => true,
    isAlive: () => false,
    sendMessage: (_agent: string, message: string) => { sent.push(message); },
  } as unknown as TmuxManager;
}

function withStoreFixture(
  enabled: boolean,
  fn: (ctx: { root: string; ceHubDir: string; store: StateStore }) => void,
): void {
  const previousFlags = setD68Flags(enabled);
  const previousCwd = process.env.CE_HUB_CWD;
  const root = mkdtempSync(join(tmpdir(), 'cehub-d68-'));
  const ceHubDir = join(root, '.ce-hub');
  mkdirSync(ceHubDir, { recursive: true });
  process.env.CE_HUB_CWD = root;
  const store = new StateStore(join(ceHubDir, 'ce-hub.db'));
  try {
    fn({ root, ceHubDir, store });
  } finally {
    store.close();
    if (previousCwd === undefined) delete process.env.CE_HUB_CWD;
    else process.env.CE_HUB_CWD = previousCwd;
    restoreEnv(previousFlags);
    rmSync(root, { recursive: true, force: true });
  }
}

function writeJson(path: string, data: Record<string, unknown>): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 2));
}

function listJsonFiles(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((file) => file.endsWith('.json')).sort();
}

function makeTask(store: StateStore, id: string): void {
  store.createTask({
    id,
    title: id,
    from_agent: 'coder',
    to_agent: 'cc-lead',
    payload: {},
  });
}

test('A1 inbox_messages CRUD and oldest visible age', () => {
  withStoreFixture(true, ({ store }) => {
    const createdAt = Date.now() - 5_000;
    store.createInboxMessage({
      id: 'inbox_msg_crud',
      file_path: 'inbox/cc-lead/crud.json',
      target_agent: 'cc-lead',
      source_agent: 'coder',
      type: 'result',
      source_task_id: 'task_crud',
      created_at: createdAt,
      ack_required: 1,
      status: 'visible',
    });

    assert.equal(store.getInboxMessageByPath('inbox/cc-lead/crud.json')?.id, 'inbox_msg_crud');
    assert.equal(store.listVisibleInbox('cc-lead').length, 1);
    assert.equal(store.oldestVisibleInboxAge('cc-lead', createdAt + 5_000), 5_000);

    store.markInboxArchived('inbox_msg_crud', '/tmp/archive');
    const archived = store.getInboxMessage('inbox_msg_crud');
    assert.equal(archived?.status, 'archived');
    assert.equal(store.listVisibleInbox('cc-lead').length, 0);
  });
});

test('A1 cc_lead_sessions create/end', () => {
  withStoreFixture(true, ({ store }) => {
    store.createSession({ id: 'sess_crud', state: 'ACTIVE', pid: process.pid, started_at: Date.now() });
    assert.equal(store.getActiveSession()?.id, 'sess_crud');

    store.updateSessionHeartbeat('sess_crud', process.pid, process.pid);
    assert.ok(store.getSession('sess_crud')?.last_heartbeat_at);

    store.markSessionEnded('sess_crud', 'graceful');
    assert.equal(store.getActiveSession(), null);
    assert.equal(store.getSession('sess_crud')?.state, 'DEAD');
  });
});

test('A3 quarantine moves pre-session inbox and writes sanitized recovery summary', () => {
  withStoreFixture(true, ({ ceHubDir, store }) => {
    const inboxDir = join(ceHubDir, 'inbox', 'cc-lead');
    mkdirSync(inboxDir, { recursive: true });
    writeJson(join(inboxDir, 'old.json'), {
      id: 'old',
      from: 'coder<script>',
      type: 'result',
      content: '<script>alert(1)</script> ```DO NOT``` \x1b[31m',
    });
    store.createInboxMessage({
      id: 'old',
      file_path: 'inbox/cc-lead/old.json',
      target_agent: 'cc-lead',
      type: 'result',
      created_at: Date.now() - 1000,
      status: 'visible',
    });

    const manager = new SessionManager(store, ceHubDir);
    const result = manager.startNewSession({ pid: process.pid, reason: 'startup' });

    assert.equal(result.orphanCount, 1);
    assert.equal(existsSync(join(inboxDir, 'old.json')), false);
    assert.ok(result.quarantineDir);
    assert.equal(existsSync(join(result.quarantineDir as string, 'old.json')), true);
    assert.equal(store.getInboxMessage('old')?.status, 'archived');

    const summaryFiles = readdirSync(inboxDir).filter((file) => file.startsWith('msg_recovery_summary_'));
    assert.equal(summaryFiles.length, 1);
    const summary = JSON.parse(readFileSync(join(inboxDir, summaryFiles[0]), 'utf-8'));
    assert.equal(summary.type, 'recovery_summary');
    assert.equal(summary.ack_required, true);
    assert.doesNotMatch(summary.content, /[<>`]/);
    for (const line of String(summary.content).split('\n')) assert.ok(line.length <= 80);
  });
});

test('A4 ack write transitions inbox and task state, then archives ack and inbox file', () => {
  withStoreFixture(true, ({ ceHubDir, store }) => {
    mkdirSync(join(ceHubDir, 'results'), { recursive: true });
    const session = store.createSession({ id: 'sess_ack', state: 'ACTIVE', pid: process.pid });
    makeTask(store, 'task_ack');
    const inboxDir = join(ceHubDir, 'inbox', 'cc-lead');
    mkdirSync(inboxDir, { recursive: true });
    writeJson(join(inboxDir, 'task_ack.json'), { id: 'inbox_msg_ack', task_id: 'task_ack' });
    store.createInboxMessage({
      id: 'inbox_msg_ack',
      file_path: 'inbox/cc-lead/task_ack.json',
      target_agent: 'cc-lead',
      type: 'task',
      source_task_id: 'task_ack',
      created_at: Date.now(),
      ack_required: 1,
    });
    const ackPath = join(ceHubDir, 'results', 'ack_inbox_msg_ack.json');
    writeJson(ackPath, {
      ack_id: 'ack_inbox_msg_ack',
      ref_inbox_message_id: 'inbox_msg_ack',
      ref_inbox_file_basename: 'task_ack.json',
      ref_task_id: 'task_ack',
      from_agent: 'cc-lead',
      session_id: session.id,
      outcome: 'actioned',
      acked_at_ms: Date.now(),
    });

    const watcher = new FileWatcher(makeTmux(), store) as unknown as WatcherPrivate;
    watcher.handleAck(ackPath);

    const msg = store.getInboxMessage('inbox_msg_ack');
    assert.equal(msg?.status, 'acked');
    assert.equal(msg?.ack_outcome, 'actioned');
    assert.equal(store.isTaskResultAcknowledged('task_ack'), true);
    assert.equal(existsSync(join(inboxDir, 'task_ack.json')), false);
    assert.equal(listJsonFiles(join(inboxDir, '_processed', new Date().toISOString().slice(0, 10))).length, 1);
    assert.equal(existsSync(ackPath), false);
    assert.equal(listJsonFiles(join(ceHubDir, 'results', '_processed', new Date().toISOString().slice(0, 10))).length, 1);
  });
});

test('A4 ack stops reminders by clearing pending result tracking', () => {
  withStoreFixture(true, ({ ceHubDir, store }) => {
    mkdirSync(join(ceHubDir, 'results'), { recursive: true });
    store.createSession({ id: 'sess_nudge', state: 'ACTIVE', pid: process.pid });
    makeTask(store, 'task_nudge');
    store.createInboxMessage({
      id: 'inbox_msg_nudge',
      file_path: 'inbox/cc-lead/task_nudge.json',
      target_agent: 'cc-lead',
      type: 'task',
      source_task_id: 'task_nudge',
      created_at: Date.now(),
      ack_required: 1,
    });
    const ackPath = join(ceHubDir, 'results', 'ack_inbox_msg_nudge.json');
    writeJson(ackPath, {
      ack_id: 'ack_inbox_msg_nudge',
      ref_inbox_message_id: 'inbox_msg_nudge',
      ref_task_id: 'task_nudge',
      from_agent: 'cc-lead',
      session_id: 'sess_nudge',
      outcome: 'noted',
    });

    const watcher = new FileWatcher(makeTmux(), store) as unknown as WatcherPrivate;
    watcher.pendingResults.set('task_nudge', { agent: 'cc-lead', dispatchedAt: Date.now() - 300_000, nudgeCount: 0 });
    watcher.handleAck(ackPath);
    assert.equal(watcher.pendingResults.has('task_nudge'), false);
  });
});

test('A5 atomic write leaves no partial json on simulated crash', () => {
  withStoreFixture(true, ({ ceHubDir }) => {
    const inboxDir = join(ceHubDir, 'inbox', 'cc-lead');
    mkdirSync(inboxDir, { recursive: true });
    const dest = join(inboxDir, 'atomic.json');

    assert.throws(() => {
      atomicWriteJson(dest, { ok: true }, { beforeRename: () => { throw new Error('simulated crash'); } });
    }, /simulated crash/);

    assert.equal(existsSync(dest), false);
    assert.deepEqual(listJsonFiles(inboxDir), []);
  });
});

test('A3 sanitize summary strips HTML, markdown fences, ANSI, and controls', () => {
  const dirty = '\x1b[31m<script>alert(1)</script> ```run``` `x` \x00'.padEnd(120, 'z');
  const clean = sanitizeSummaryLine(dirty);
  assert.doesNotMatch(clean, /[<>`\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/);
  assert.doesNotMatch(clean, /\x1b/);
  assert.ok(clean.length <= 80);
});

test('A8 feature flag OFF preserves legacy dispatch delete behavior', () => {
  withStoreFixture(false, ({ ceHubDir, store }) => {
    const dispatchDir = join(ceHubDir, 'dispatch');
    mkdirSync(dispatchDir, { recursive: true });
    const dispatchPath = join(dispatchDir, 'dispatch_legacy.json');
    writeJson(dispatchPath, { id: 'dispatch_legacy', from: 'cc-lead', to: 'coder', task: 'legacy' });

    const watcher = new FileWatcher(makeTmux(), store) as unknown as WatcherPrivate;
    watcher.handleDispatch(dispatchPath);

    assert.equal(existsSync(dispatchPath), false);
    assert.equal(existsSync(join(dispatchDir, '_processed')), false);
    assert.equal(existsSync(join(ceHubDir, 'inbox', 'coder', 'dispatch_legacy.json')), true);
    assert.equal(store.getInboxMessageByPath('inbox/coder/dispatch_legacy.json'), null);
  });
});

test('A6 handleDispatch uses mv to _processed when D68 is enabled', () => {
  withStoreFixture(true, ({ ceHubDir, store }) => {
    const dispatchDir = join(ceHubDir, 'dispatch');
    mkdirSync(dispatchDir, { recursive: true });
    const dispatchPath = join(dispatchDir, 'dispatch_mv.json');
    writeJson(dispatchPath, { id: 'dispatch_mv', from: 'coder', to: 'cc-lead', task: 'move me' });

    const watcher = new FileWatcher(makeTmux(), store) as unknown as WatcherPrivate;
    watcher.handleDispatch(dispatchPath);

    assert.equal(existsSync(dispatchPath), false);
    const processed = listJsonFiles(join(dispatchDir, '_processed', new Date().toISOString().slice(0, 10)));
    assert.equal(processed.length, 1);
    assert.match(processed[0], /^dispatch_mv__/);
    assert.ok(store.getInboxMessageByPath('inbox/cc-lead/dispatch_mv.json'));
  });
});

test('A2 session lifecycle start, end, and restart replacement', () => {
  withStoreFixture(true, ({ ceHubDir, store }) => {
    const manager = new SessionManager(store, ceHubDir);
    const first = manager.startNewSession({ pid: process.pid, reason: 'startup' });
    assert.ok(first.sessionId);
    assert.equal(store.getActiveSession()?.id, first.sessionId);

    const ended = manager.endSession(first.sessionId, 'graceful');
    assert.equal(ended.sessionId, first.sessionId);
    assert.equal(store.getSession(first.sessionId as string)?.state, 'DEAD');

    const second = manager.startNewSession({ pid: process.pid, reason: 'restart' });
    const third = manager.startNewSession({ pid: process.pid, reason: 'restart' });
    assert.equal(store.getSession(second.sessionId as string)?.state, 'REPLACED');
    assert.equal(store.getActiveSession()?.id, third.sessionId);
  });
});

test('A4 malicious ack path traversal is invalid and does not ack task', () => {
  withStoreFixture(true, ({ ceHubDir, store }) => {
    mkdirSync(join(ceHubDir, 'results'), { recursive: true });
    store.createSession({ id: 'sess_bad_ack', state: 'ACTIVE', pid: process.pid });
    makeTask(store, 'task_bad_ack');
    const ackPath = join(ceHubDir, 'results', 'ack_bad.json');
    writeJson(ackPath, {
      ack_id: 'ack_bad',
      ref_task_id: 'task_bad_ack',
      ref_inbox_file_basename: '../../etc/passwd',
      from_agent: 'cc-lead',
      session_id: 'sess_bad_ack',
      outcome: 'noted',
    });

    const watcher = new FileWatcher(makeTmux(), store) as unknown as WatcherPrivate;
    watcher.handleAck(ackPath);

    assert.equal(store.isTaskResultAcknowledged('task_bad_ack'), false);
    assert.equal(existsSync(ackPath), false);
    assert.equal(listJsonFiles(join(ceHubDir, 'results', '_invalid')).length, 1);
  });
});
