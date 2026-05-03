import { watch, readFileSync, writeFileSync, appendFileSync, readdirSync, unlinkSync, existsSync, mkdirSync, renameSync } from 'node:fs';
import { join, dirname, basename } from 'node:path';
import type { TmuxManager } from './tmux-manager.js';
import type { StateStore } from './state-store.js';
import type { TaskEngine } from './task-engine.js';
import { D68_CONFIG, d68PrAEnabled } from './config.js';
import { atomicWriteJson } from './quarantine.js';

// Lazy: read at call time, not module load time (avoids ESM import hoisting issue)
function getCwd() { return process.env.CE_HUB_CWD || process.cwd(); }
function getCeHubDir() { return join(getCwd(), '.ce-hub'); }

function ensureDir(dir: string) { if (!existsSync(dir)) mkdirSync(dir, { recursive: true }); }

function appendRaw(filename: string, data: Record<string, unknown>): void {
  const rawDir = join(getCeHubDir(), 'raw');
  ensureDir(rawDir);
  try {
    appendFileSync(join(rawDir, filename), JSON.stringify({ ...data, _archived_at: new Date().toISOString() }) + '\n');
  } catch (err) {
    console.error(`[FileWatcher] failed to archive raw data to ${filename}:`, err);
  }
}

// Write attention state for a window (triggers nav bar highlight in TUI v2)
function writeAttention(agentName: string, hasAttention: boolean): void {
  const stateDir = join(getCeHubDir(), 'state');
  ensureDir(stateDir);
  const attnFile = join(stateDir, 'attention.json');
  let attn: Record<string, boolean> = {};
  if (existsSync(attnFile)) {
    try { attn = JSON.parse(readFileSync(attnFile, 'utf-8')); } catch {}
  }
  attn[agentName] = hasAttention;
  try { writeFileSync(attnFile, JSON.stringify(attn, null, 2)); } catch {}
}

function readJson(path: string): Record<string, unknown> | null {
  try { return JSON.parse(readFileSync(path, 'utf-8')); } catch (err) {
    console.error(`[FileWatcher] failed to parse JSON: ${path}:`, err);
    return null;
  }
}

// L1 — Strict string check helper. Rejects "", 0, {}, non-string truthy values.
function firstNonEmptyString(...vals: unknown[]): string | undefined {
  for (const v of vals) {
    if (typeof v === 'string') {
      const trimmed = v.trim();
      if (trimmed.length > 0) return trimmed;
    }
  }
  return undefined;
}

// Q2 — Build an archive filename that won't collide with previous archives of
// the same source basename. Suffix combines wall-clock ms + pid + small random
// string for collision resistance even within the same millisecond.
export function uniqueArchivePath(dir: string, sourceName: string): string {
  const dotIdx = sourceName.lastIndexOf('.');
  const stem = dotIdx > 0 ? sourceName.slice(0, dotIdx) : sourceName;
  const ext = dotIdx > 0 ? sourceName.slice(dotIdx) : '';
  const rand = Math.random().toString(36).slice(2, 8);
  const suffix = `${Date.now()}_${process.pid}_${rand}`;
  return join(dir, `${stem}__${suffix}${ext}`);
}

export class FileWatcher {
  private tmux: TmuxManager;
  private store: StateStore;
  private engine: TaskEngine | null = null;
  private watchers: ReturnType<typeof watch>[] = [];
  private pendingResults = new Map<string, { agent: string; dispatchedAt: number; nudgeCount: number }>();
  private nudgeTimer: ReturnType<typeof setInterval> | null = null;
  private taskTimeoutTimer: ReturnType<typeof setInterval> | null = null;
  // 30s poll fallback timer (fs.watch is unreliable on macOS). Stored as a
  // class field so stop() can clearInterval and avoid leaking the interval
  // when the daemon shuts down or restarts.
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  // Dedup: track result files currently being processed to prevent double-handling
  // (watch() event + 30s poll can race on the same file before unlinkSync fires)
  private processingDispatch = new Set<string>();
  private processingResults = new Set<string>();
  private processingAcks = new Set<string>();
  // Q3+Q7 — cross-call idempotency: side effects already executed for this file.
  // Set after first successful pass through the side-effect block; cleared once
  // the file is finally archived or quarantined. Prevents duplicate appendRaw /
  // DB updates / inbox forwarding when an archive rename fails and the 30s poll
  // re-enters handleResult.
  private processedSideEffects = new Set<string>();
  // Q3+Q7 — cross-call retry counter for archive renames. After
  // MAX_RENAME_RETRIES failed attempts the file is force-quarantined to
  // _archive_failed/ with a marker in raw/archive_failures.jsonl.
  private failedRenameCount = new Map<string, number>();
  private static readonly MAX_RENAME_RETRIES = 5;

  constructor(tmux: TmuxManager, store: StateStore) {
    this.tmux = tmux;
    this.store = store;
  }

  // Set engine reference (called after both are initialized, avoids circular dep)
  setEngine(engine: TaskEngine): void {
    this.engine = engine;
  }

  start(): void {
    const dispatchDir = join(getCeHubDir(), 'dispatch');
    const resultsDir = join(getCeHubDir(), 'results');
    ensureDir(dispatchDir);
    ensureDir(resultsDir);

    // Watch dispatch directory
    this.watchers.push(watch(dispatchDir, (event, filename) => {
      if ((event === 'rename' || event === 'change') && filename?.endsWith('.json')) {
        const filePath = join(dispatchDir, filename);
        if (!existsSync(filePath)) return;
        setTimeout(() => this.handleDispatch(filePath), 200); // debounce
      }
    }));

    // Watch results directory
    this.watchers.push(watch(resultsDir, (event, filename) => {
      if ((event === 'rename' || event === 'change') && filename?.endsWith('.json')) {
        const filePath = join(resultsDir, filename);
        if (!existsSync(filePath)) return;
        setTimeout(() => this.handleResultsFile(filePath), 200);
      }
    }));

    // Process any existing dispatch/results files on startup
    this.scanOnce();

    // Periodically nudge agents that haven't reported results
    this.nudgeTimer = setInterval(() => this.nudgePending(), 120_000); // every 2 min

    // Periodically timeout stuck tasks
    this.taskTimeoutTimer = setInterval(() => this.timeoutStuckTasks(), 300_000); // every 5 min

    // Polling fallback: fs.watch is unreliable on macOS, scan every 30s.
    // Stored on `this.pollTimer` so stop() can clearInterval (D69 round 2 — GPT 5.5).
    this.pollTimer = setInterval(() => {
      this.scanOnce();
    }, 30_000);

    console.log(`[FileWatcher] watching ${dispatchDir} and ${resultsDir} (+ 30s poll fallback${D68_CONFIG.ACKS ? ', D68 acks' : ''})`);
  }

  scanOnce(): void {
    const dispatchDir = join(getCeHubDir(), 'dispatch');
    const resultsDir = join(getCeHubDir(), 'results');
    this.processExisting(dispatchDir, (f) => this.handleDispatch(f));
    this.processExisting(resultsDir, (f) => this.handleResultsFile(f));
  }

  private processExisting(dir: string, handler: (path: string) => void): void {
    try {
      for (const f of readdirSync(dir).filter(f => f.endsWith('.json'))) {
        handler(join(dir, f));
      }
    } catch {}
  }

  private handleResultsFile(filePath: string): void {
    if (D68_CONFIG.ACKS && basename(filePath).startsWith('ack_')) {
      this.handleAck(filePath);
      return;
    }
    this.handleResult(filePath);
  }

  private handleDispatch(filePath: string): void {
    if (this.processingDispatch.has(filePath)) return;
    this.processingDispatch.add(filePath);

    try {
      const data = readJson(filePath);
      if (!data) return;

      const from = (data.from || data.dispatched_by || "cc-lead") as string;
      const to = (data.to || data.dispatched_to) as string;
      const task = data.task as string;
      const taskId = data.id as string || `dispatch_${Date.now()}`;
      const priority = (data.priority as number) || 1;
      const d68Tracked = d68PrAEnabled();

      if (!this.processedSideEffects.has(filePath)) {
        console.log(`[FileWatcher] dispatch: ${from} → ${to}: ${task?.slice(0, 60)}`);

        // Create task in DB
        this.store.createTask({
          id: taskId,
          title: task || 'Dispatched task', from_agent: from, to_agent: to,
          priority, payload: data as Record<string, unknown>,
        });

        // Log event
        this.store.createEvent({ type: 'dispatch', source: from, target: to, payload: { task, taskId } });

        // Ensure target agent inbox exists
        const inboxDir = join(getCeHubDir(), 'inbox', to);
        ensureDir(inboxDir);

        // Write task to target agent's inbox — include full dispatch payload so agent sees all fields
        const inboxFile = join(inboxDir, `${taskId}.json`);
        const inboxMessageId = `inbox_msg_${taskId}_${Date.now()}`;
        const messageId = d68Tracked && to === 'cc-lead' ? inboxMessageId : taskId;
        const inboxPayload = {
          id: messageId, inbox_message_id: inboxMessageId, task_id: taskId,
          from, to, type: 'task', content: task,
          context: data.context || '',
          objective: data.objective || '',
          priority: data.priority || 1,
          expected_output: data.expected_output || '',
          success_criteria: data.success_criteria || '',
          payload: data,
          created_at: new Date().toISOString(),
          ack_required: d68Tracked && to === 'cc-lead',
        };
        atomicWriteJson(inboxFile, inboxPayload);

        if (d68Tracked) {
          const ackRequired = to === 'cc-lead' ? 1 : 0;
          const createdAt = Date.now();
          this.store.createInboxMessage({
            id: inboxMessageId,
            file_path: `inbox/${to}/${taskId}.json`,
            target_agent: to,
            source_agent: from,
            type: 'task',
            source_task_id: taskId,
            target_session_id: to === 'cc-lead' ? this.store.getActiveSession()?.id ?? null : null,
            created_at: createdAt,
            priority: priority <= 0 ? 'p0' : priority === 1 ? 'high' : 'normal',
            ack_required: ackRequired,
            ack_deadline_at: ackRequired ? createdAt + 15 * 60_000 : null,
            status: 'visible',
            metadata: { dispatch_file: basename(filePath) },
          });
        }

        // Start target agent if not running
        this.tmux.startAgent(to);

        // If agent is already running, notify it to check inbox
        if (this.tmux.isAlive(to)) {
          // Give it a moment to start, then send a nudge
          setTimeout(() => {
            this.tmux.sendMessage(to, `You have a new task in .ce-hub/inbox/${to}/. Read the JSON file and execute it.`);
          }, 3000);
        }

        // Archive to raw/ for wiki compiler
        appendRaw('dispatches.jsonl', { id: taskId, from, to, task, priority });

        // Set attention flag for the target agent (triggers nav bar highlight in TUI v2)
        writeAttention(to, true);

        // Track pending result
        this.pendingResults.set(taskId, { agent: to, dispatchedAt: Date.now(), nudgeCount: 0 });
        this.processedSideEffects.add(filePath);
      }

      // Move dispatch file to processed when D68 is enabled; legacy flag-off path deletes.
      if (d68Tracked) {
        this.archiveWithRetry(filePath, join(getCeHubDir(), 'dispatch', '_processed', this.dateStamp()), taskId);
      } else {
        try { unlinkSync(filePath); } catch {}
        this.processedSideEffects.delete(filePath);
      }
    } finally {
      this.processingDispatch.delete(filePath);
    }
  }

  // Test seam: rename wrapper. Override on instance for tests.
  protected safeRenameSync(src: string, dst: string): void {
    renameSync(src, dst);
  }

  private dateStamp(): string {
    return new Date().toISOString().slice(0, 10);
  }

  private archiveDirect(filePath: string, targetDir: string): boolean {
    ensureDir(targetDir);
    const dst = uniqueArchivePath(targetDir, basename(filePath));
    try {
      this.safeRenameSync(filePath, dst);
      return true;
    } catch (err) {
      console.error(`[FileWatcher] failed to move ${filePath} -> ${targetDir}:`, err);
      return false;
    }
  }

  private handleAck(filePath: string): void {
    if (!D68_CONFIG.ACKS) return;
    if (this.processingAcks.has(filePath)) return;
    this.processingAcks.add(filePath);

    try {
      const ack = readJson(filePath);
      if (!ack) {
        this.archiveDirect(filePath, join(getCeHubDir(), 'results', '_invalid'));
        return;
      }

      const invalidReason = this.validateAck(ack);
      if (invalidReason) {
        console.warn(`[FileWatcher] invalid ack ${basename(filePath)}: ${invalidReason}`);
        this.store.createEvent({
          type: 'ack.invalid',
          source: 'file-watcher',
          payload: { file: basename(filePath), reason: invalidReason },
        });
        this.archiveDirect(filePath, join(getCeHubDir(), 'results', '_invalid'));
        return;
      }

      const refInboxMessageId = firstNonEmptyString(ack.ref_inbox_message_id);
      // `ref_task_id` names the original dispatch task this ack refers to; it is
      // not a result-file id.
      const refTaskId = firstNonEmptyString(ack.ref_task_id, ack.ref_dispatch);
      const sessionId = firstNonEmptyString(ack.session_id) as string;
      const outcome = firstNonEmptyString(ack.outcome) as string;
      const ackedAt = typeof ack.acked_at_ms === 'number' ? ack.acked_at_ms : Date.now();
      const inboxMessage = refInboxMessageId ? this.store.getInboxMessage(refInboxMessageId) : null;

      if (refInboxMessageId && !this.store.markInboxAcked(refInboxMessageId, sessionId, outcome)) {
        console.warn(`[FileWatcher] rejected ack ${basename(filePath)}: inbox message is no longer ackable`);
        this.store.createEvent({
          type: 'ack.rejected',
          source: 'file-watcher',
          payload: { file: basename(filePath), ref_inbox_message_id: refInboxMessageId, session_id: sessionId },
        });
        this.archiveDirect(filePath, join(getCeHubDir(), 'results', '_invalid'));
        return;
      }
      if (refTaskId) {
        this.store.markTaskResultAcknowledged(refTaskId, sessionId, ackedAt);
        this.pendingResults.delete(refTaskId);
      }

      const refBasename = inboxMessage
        ? (inboxMessage.inbox_file_basename || basename(inboxMessage.file_path))
        : firstNonEmptyString(ack.ref_inbox_file_basename);
      if (refBasename) {
        const inboxFile = join(getCeHubDir(), 'inbox', 'cc-lead', refBasename);
        if (existsSync(inboxFile)) {
          this.archiveDirect(inboxFile, join(getCeHubDir(), 'inbox', 'cc-lead', '_processed', this.dateStamp()));
        }
      }

      this.archiveDirect(filePath, join(getCeHubDir(), 'results', '_processed', this.dateStamp()));
      this.store.createEvent({
        type: 'ack.processed',
        source: 'file-watcher',
        target: 'cc-lead',
        payload: {
          ack_id: firstNonEmptyString(ack.ack_id),
          ref_inbox_message_id: refInboxMessageId,
          ref_task_id: refTaskId,
          session_id: sessionId,
          outcome,
        },
      });
    } finally {
      this.processingAcks.delete(filePath);
    }
  }

  private validateAck(ack: Record<string, unknown>): string | null {
    const ackId = firstNonEmptyString(ack.ack_id);
    const sessionId = firstNonEmptyString(ack.session_id);
    const outcome = firstNonEmptyString(ack.outcome);
    const refInboxMessageId = firstNonEmptyString(ack.ref_inbox_message_id);
    const refTaskId = firstNonEmptyString(ack.ref_task_id, ack.ref_dispatch);
    const fromAgent = firstNonEmptyString(ack.from_agent);
    const allowedOutcomes = new Set(['noted', 'actioned', 'dispatched', 'deferred']);

    if (!ackId) return 'missing ack_id';
    if (!sessionId) return 'missing session_id';
    if (!outcome || !allowedOutcomes.has(outcome)) return 'invalid outcome';
    if (fromAgent && fromAgent !== 'cc-lead') return 'from_agent must be cc-lead';
    if (!refInboxMessageId && !refTaskId) return 'missing ref';
    if (!this.store.getSession(sessionId)) return 'unknown session_id';
    const inboxMessage = refInboxMessageId ? this.store.getInboxMessage(refInboxMessageId) : null;
    if (refInboxMessageId && !inboxMessage) return 'unknown inbox message';
    if (refTaskId && !this.store.getTask(refTaskId)) return 'unknown task';

    const refBasename = firstNonEmptyString(ack.ref_inbox_file_basename);
    if (refBasename) {
      if (refBasename !== basename(refBasename)) return 'unsafe inbox basename';
      if (refBasename.includes('..') || refBasename.includes('/') || refBasename.includes('\\')) return 'unsafe inbox basename';
    }
    if (inboxMessage) {
      if (inboxMessage.status !== 'visible') return 'inbox message is not visible';
      if (inboxMessage.ack_required !== 1) return 'inbox message does not require ack';
      if (inboxMessage.target_session_id !== sessionId) return 'session_id does not match inbox message';
      const expectedBasename = inboxMessage.inbox_file_basename || basename(inboxMessage.file_path);
      if (refBasename && refBasename !== expectedBasename) return 'inbox basename mismatch';
    }

    return null;
  }

  /**
   * Q3+Q7 — Archive `filePath` into `targetDir` with retry/quarantine semantics.
   * Returns true if the source file is no longer at `filePath` (either archived
   * successfully or force-quarantined to `_archive_failed/`). Returns false if
   * the rename failed transiently and the caller should leave the file in place
   * for the next 30s poll cycle to retry.
   *
   * Retry counter is keyed by source path and persists across handleResult
   * invocations. After MAX_RENAME_RETRIES failures the file is force-moved to
   * `.ce-hub/results/_archive_failed/` and a marker is written to
   * `raw/archive_failures.jsonl`. Counter is cleared on success or quarantine.
   */
  private archiveWithRetry(filePath: string, targetDir: string, taskId?: string): boolean {
    ensureDir(targetDir);
    const dst = uniqueArchivePath(targetDir, basename(filePath));
    try {
      this.safeRenameSync(filePath, dst);
      this.failedRenameCount.delete(filePath);
      this.processedSideEffects.delete(filePath);
      return true;
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      const count = (this.failedRenameCount.get(filePath) ?? 0) + 1;
      this.failedRenameCount.set(filePath, count);
      console.error(
        `[FileWatcher] archive failed (${count}/${FileWatcher.MAX_RENAME_RETRIES}) ${filePath} → ${targetDir}: ${errMsg}`
      );

      if (count >= FileWatcher.MAX_RENAME_RETRIES) {
        const failedDir = join(getCeHubDir(), 'results', '_archive_failed');
        ensureDir(failedDir);
        const failedPath = uniqueArchivePath(failedDir, basename(filePath));
        let quarantined = false;
        try {
          this.safeRenameSync(filePath, failedPath);
          quarantined = true;
        } catch (qErr: unknown) {
          const qMsg = qErr instanceof Error ? qErr.message : String(qErr);
          console.error(`[FileWatcher] quarantine rename also failed for ${filePath}: ${qMsg}`);
        }
        appendRaw('archive_failures.jsonl', {
          source: filePath,
          target_dir: targetDir,
          quarantined_to: quarantined ? failedPath : null,
          error: errMsg,
          attempts: count,
          task_id: taskId,
          ts: Date.now(),
        });
        this.failedRenameCount.delete(filePath);
        this.processedSideEffects.delete(filePath);
        // Even if quarantine renameSync also failed (truly broken FS), clear
        // the counters and surrender — repeated retries would only spam logs.
        //
        // TODO(follow-up): Tier 3 quarantine rename 也失败时当前清空 idempotency state
        // 并 return true，但源文件仍在 results/ → 30s poll 重新进入 → 重复处理。
        // 触发条件需 disk full 且 _archive_failed/ 同时不可写（实际触发概率极低）。
        // 修复方案（reviewer raw/code-reviewer/pr23-review-20260501.md §E）：
        //   - 保留 sticky guard（不删 failedRenameCount / processedSideEffects）
        //   - 或写 .surrender.json marker 让 processExisting 跳过
        // cc-lead 2026-05-02 决策：暂不修，等真触发或 daemon 改造时统一处理
        return true;
      }
      return false;
    }
  }

  private handleResult(filePath: string): void {
    // Dedup guard: skip if already being processed (watch event + poll race)
    if (this.processingResults.has(filePath)) return;
    this.processingResults.add(filePath);

    try {
      const data = readJson(filePath);
      if (!data) return;

      const from = firstNonEmptyString(data.from, data.dispatched_by) ?? 'cc-lead';
      const taskId = firstNonEmptyString(data.task_id, data.ref_dispatch, data.ref_task, data.dispatch_id);
      const status = data.status as string;
      const summary = (data.summary as string) || (data.content as string) || '';
      const outputFiles = data.output_files as string[] || [];

      const sideEffectsAlreadyRun = this.processedSideEffects.has(filePath);
      let originAgent: string | undefined;
      let undeliverable = false;

      if (!sideEffectsAlreadyRun) {
        console.log(`[FileWatcher] result: ${from} completed ${taskId ?? '(no-task-id)'}: ${status}`);

        // Always archive to raw/ — evidence preserved even for orphans / undeliverable
        appendRaw('results.jsonl', { from, task_id: taskId, status, summary, output_files: outputFiles });

        this.store.createEvent({
          type: 'result', source: from,
          payload: { taskId, status, summary, outputFiles },
        });

        if (taskId) {
          // Clear from pending tracking
          this.pendingResults.delete(taskId);

          // Update task in DB if known
          const task = this.store.getTask(taskId);
          if (task) {
            this.store.updateTask(taskId, {
              status: status === 'done' ? 'done' : 'failed',
              result: data as Record<string, unknown>,
              completed_at: Date.now(),
            });
          }

          const dataTo = firstNonEmptyString(data.to);
          originAgent = task?.from_agent ?? dataTo;

          if (originAgent) {
            // Forward result to originator's inbox + nudge + attention
            const originInbox = join(getCeHubDir(), 'inbox', originAgent);
            ensureDir(originInbox);
            const now = Date.now();
            const resultMessageId = `inbox_msg_result_${from}_${now}`;
            const resultFile = `result_${from}_${now}.json`;
            const resultPayload = {
              id: d68PrAEnabled() && originAgent === 'cc-lead' ? resultMessageId : `result_${now}`,
              inbox_message_id: resultMessageId,
              from, to: originAgent, type: 'result',
              content: `[${from} ${status}] ${summary || '(no summary)'}`, task_id: taskId,
              output_files: outputFiles, created_at: new Date(now).toISOString(),
              ack_required: d68PrAEnabled() && originAgent === 'cc-lead',
            };
            atomicWriteJson(join(originInbox, resultFile), resultPayload);

            if (d68PrAEnabled()) {
              const ackRequired = originAgent === 'cc-lead' ? 1 : 0;
              this.store.createInboxMessage({
                id: resultMessageId,
                file_path: `inbox/${originAgent}/${resultFile}`,
                target_agent: originAgent,
                source_agent: from,
                type: 'result',
                source_task_id: taskId,
                target_session_id: originAgent === 'cc-lead' ? this.store.getActiveSession()?.id ?? null : null,
                created_at: now,
                priority: 'normal',
                ack_required: ackRequired,
                ack_deadline_at: ackRequired ? now + 15 * 60_000 : null,
                status: 'visible',
                metadata: { result_file: basename(filePath), status },
              });
            }

            if (this.tmux.isAlive(originAgent)) {
              this.tmux.sendMessage(originAgent, `Task completed by ${from}: ${summary?.slice(0, 200)}`);
            }

            writeAttention(originAgent, true);
          } else {
            // L2 — Undeliverable: task missing from DB AND no data.to.
            // Don't silently drop into _processed/; emit a marker + dedicated event.
            undeliverable = true;
            appendRaw('results.jsonl', {
              type: 'undeliverable', from, task_id: taskId, summary, output_files: outputFiles,
            });
            this.store.createEvent({
              type: 'result_undeliverable', source: from,
              payload: { taskId, status, summary, reason: 'no_origin_agent_resolvable' },
            });
            console.warn(`[FileWatcher] undeliverable result for task ${taskId}: no origin agent resolvable`);
          }

          // Trigger downstream DAG tasks
          if (status === 'done' && this.engine) {
            try { this.engine.triggerDownstream(taskId); } catch (err) {
              console.error(`[FileWatcher] failed to trigger downstream for ${taskId}:`, err);
            }
          }

          // Clean up the dispatch inbox file we received from `from`
          const inboxFile = join(getCeHubDir(), 'inbox', from, `${taskId}.json`);
          if (existsSync(inboxFile) && d68PrAEnabled()) {
            this.archiveDirect(inboxFile, join(getCeHubDir(), 'inbox', from, '_processed', this.dateStamp()));
          } else {
            try { unlinkSync(inboxFile); } catch {}
          }
        }

        this.processedSideEffects.add(filePath);
      } else {
        // Side effects already ran on a previous (failed) attempt; only re-derive
        // routing inputs needed for the archive destination decision.
        if (taskId) {
          const task = this.store.getTask(taskId);
          const dataTo = firstNonEmptyString(data.to);
          originAgent = task?.from_agent ?? dataTo;
          undeliverable = !originAgent;
        }
      }

      // Phase 2: Archive (with retry / quarantine)
      let archiveDir: string;
      if (!taskId) {
        archiveDir = join(getCeHubDir(), 'results', '_orphan_no_task_id');
      } else if (undeliverable) {
        archiveDir = join(getCeHubDir(), 'inbox', '_undeliverable');
      } else {
        archiveDir = join(getCeHubDir(), 'results', '_processed');
      }

      this.archiveWithRetry(filePath, archiveDir, taskId);
      // Note: archiveWithRetry returns false on transient failure; the file
      // remains at filePath and the next 30s poll will re-enter handleResult,
      // skip side effects (processedSideEffects guard), and retry the rename.
    } finally {
      // Always release in-tick lock — cross-call retry counter handles persistent failures.
      this.processingResults.delete(filePath);
    }
  }

  private nudgePending(): void {
    const now = Date.now();
    for (const [taskId, info] of this.pendingResults) {
      if (D68_CONFIG.ACKS && this.store.isTaskResultAcknowledged(taskId)) {
        this.pendingResults.delete(taskId);
        continue;
      }
      const ageMin = (now - info.dispatchedAt) / 60_000;
      // Only nudge if >2 min old and max 3 nudges
      if (ageMin < 2 || info.nudgeCount >= 3) continue;
      if (this.tmux.isAlive(info.agent)) {
        console.log(`[FileWatcher] nudging ${info.agent} for pending task ${taskId} (${Math.round(ageMin)}min, nudge #${info.nudgeCount + 1})`);
        this.tmux.sendMessage(info.agent,
          `Reminder: pending task ${taskId}. Check .ce-hub/inbox/${info.agent}/ and write result to .ce-hub/results/ when done.`
        );
        info.nudgeCount++;
      }
      // Give up after 30 min
      if (ageMin > 30) {
        console.log(`[FileWatcher] giving up on ${taskId} from ${info.agent} after 30min`);
        this.pendingResults.delete(taskId);
      }
    }
  }

  private timeoutStuckTasks(): void {
    const TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes
    const tasks = this.store.listTasks({ status: 'in_progress' as any });
    const now = Date.now();
    for (const t of tasks) {
      const age = now - (t.started_at || t.created_at);
      if (age > TIMEOUT_MS) {
        console.warn(`[FileWatcher] task ${t.id} timed out after ${Math.round(age / 60000)}min, marking as failed`);
        this.store.updateTask(t.id, { status: 'failed', error: `Timed out after ${Math.round(age / 60000)} minutes`, completed_at: now });
        this.store.createEvent({ type: 'task.timeout', source: 'file-watcher', target: t.to_agent, payload: { taskId: t.id } });
        this.pendingResults.delete(t.id);
      }
    }
  }

  stop(): void {
    if (this.nudgeTimer) { clearInterval(this.nudgeTimer); this.nudgeTimer = null; }
    if (this.taskTimeoutTimer) { clearInterval(this.taskTimeoutTimer); this.taskTimeoutTimer = null; }
    if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
    for (const w of this.watchers) w.close();
    this.watchers = [];
  }
}
