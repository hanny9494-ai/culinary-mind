import { watch, readFileSync, writeFileSync, appendFileSync, readdirSync, unlinkSync, existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { TmuxManager } from './tmux-manager.js';
import type { StateStore } from './state-store.js';
import type { TaskEngine } from './task-engine.js';

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

function readJson(path: string): Record<string, unknown> | null {
  try { return JSON.parse(readFileSync(path, 'utf-8')); } catch (err) {
    console.error(`[FileWatcher] failed to parse JSON: ${path}:`, err);
    return null;
  }
}

export class FileWatcher {
  private tmux: TmuxManager;
  private store: StateStore;
  private engine: TaskEngine | null = null;
  private watchers: ReturnType<typeof watch>[] = [];
  private pendingResults = new Map<string, { agent: string; dispatchedAt: number; nudgeCount: number }>();
  private nudgeTimer: ReturnType<typeof setInterval> | null = null;
  private taskTimeoutTimer: ReturnType<typeof setInterval> | null = null;

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
      if (event === 'rename' && filename?.endsWith('.json')) {
        const filePath = join(dispatchDir, filename);
        if (!existsSync(filePath)) return;
        setTimeout(() => this.handleDispatch(filePath), 200); // debounce
      }
    }));

    // Watch results directory
    this.watchers.push(watch(resultsDir, (event, filename) => {
      if (event === 'rename' && filename?.endsWith('.json')) {
        const filePath = join(resultsDir, filename);
        if (!existsSync(filePath)) return;
        setTimeout(() => this.handleResult(filePath), 200);
      }
    }));

    // Process any existing dispatch/results files on startup
    this.processExisting(dispatchDir, (f) => this.handleDispatch(f));
    this.processExisting(resultsDir, (f) => this.handleResult(f));

    // Periodically nudge agents that haven't reported results
    this.nudgeTimer = setInterval(() => this.nudgePending(), 120_000); // every 2 min

    // Periodically timeout stuck tasks
    this.taskTimeoutTimer = setInterval(() => this.timeoutStuckTasks(), 300_000); // every 5 min

    console.log(`[FileWatcher] watching ${dispatchDir} and ${resultsDir}`);
  }

  private processExisting(dir: string, handler: (path: string) => void): void {
    try {
      for (const f of readdirSync(dir).filter(f => f.endsWith('.json'))) {
        handler(join(dir, f));
      }
    } catch {}
  }

  private handleDispatch(filePath: string): void {
    const data = readJson(filePath);
    if (!data) return;

    const from = data.from as string;
    const to = data.to as string;
    const task = data.task as string;
    const taskId = data.id as string || `dispatch_${Date.now()}`;
    const priority = (data.priority as number) || 1;

    console.log(`[FileWatcher] dispatch: ${from} → ${to}: ${task?.slice(0, 60)}`);

    // Create task in DB
    this.store.createTask({
      title: task || 'Dispatched task', from_agent: from, to_agent: to,
      priority, payload: data as Record<string, unknown>,
    });

    // Log event
    this.store.createEvent({ type: 'dispatch', source: from, target: to, payload: { task, taskId } });

    // Ensure target agent inbox exists
    const inboxDir = join(getCeHubDir(), 'inbox', to);
    ensureDir(inboxDir);

    // Write task to target agent's inbox
    const inboxFile = join(inboxDir, `${taskId}.json`);
    writeFileSync(inboxFile, JSON.stringify({
      id: taskId, from, type: 'task', content: task,
      context: data.context || '', created_at: new Date().toISOString(),
    }, null, 2));

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

    // Track pending result
    this.pendingResults.set(taskId, { agent: to, dispatchedAt: Date.now(), nudgeCount: 0 });

    // Move dispatch file to processed (or delete)
    try { unlinkSync(filePath); } catch {}
  }

  private handleResult(filePath: string): void {
    const data = readJson(filePath);
    if (!data) return;

    const from = data.from as string;
    const taskId = data.task_id as string;
    const status = data.status as string;
    const summary = data.summary as string;
    const outputFiles = data.output_files as string[] || [];

    console.log(`[FileWatcher] result: ${from} completed ${taskId}: ${status}`);

    // Clear from pending
    if (taskId) this.pendingResults.delete(taskId);

    // Update task in DB
    if (taskId) {
      const task = this.store.getTask(taskId);
      if (task) {
        this.store.updateTask(taskId, {
          status: status === 'done' ? 'done' : 'failed',
          result: data as Record<string, unknown>,
          completed_at: Date.now(),
        });
      }
    }

    // Log event
    this.store.createEvent({
      type: 'result', source: from,
      payload: { taskId, status, summary, outputFiles },
    });

    // Notify originating agent (from task record)
    if (taskId) {
      const task = this.store.getTask(taskId);
      if (task && task.from_agent) {
        const originInbox = join(getCeHubDir(), 'inbox', task.from_agent);
        ensureDir(originInbox);
        writeFileSync(join(originInbox, `result_${from}_${Date.now()}.json`), JSON.stringify({
          id: `result_${Date.now()}`, from, type: 'result',
          content: `[${from} ${status}] ${summary}`, task_id: taskId,
          output_files: outputFiles, created_at: new Date().toISOString(),
        }, null, 2));

        // Nudge originating agent
        if (this.tmux.isAlive(task.from_agent)) {
          this.tmux.sendMessage(task.from_agent, `Task completed by ${from}: ${summary?.slice(0, 200)}`);
        }
      }
    }

    // Archive to raw/ for wiki compiler
    appendRaw('results.jsonl', { from, task_id: taskId, status, summary, output_files: outputFiles });

    // Trigger downstream DAG tasks
    if (taskId && status === 'done' && this.engine) {
      try { this.engine.triggerDownstream(taskId); } catch (err) {
        console.error(`[FileWatcher] failed to trigger downstream for ${taskId}:`, err);
      }
    }

    // Clean up inbox file for this task
    if (taskId) {
      const inboxFile = join(getCeHubDir(), 'inbox', from, `${taskId}.json`);
      try { unlinkSync(inboxFile); } catch {}
    }
  }

  private nudgePending(): void {
    const now = Date.now();
    for (const [taskId, info] of this.pendingResults) {
      const ageMin = (now - info.dispatchedAt) / 60_000;
      // Only nudge if >2 min old and max 3 nudges
      if (ageMin < 2 || info.nudgeCount >= 3) continue;
      if (this.tmux.isAlive(info.agent)) {
        console.log(`[FileWatcher] nudging ${info.agent} for pending task ${taskId} (${Math.round(ageMin)}min, nudge #${info.nudgeCount + 1})`);
        this.tmux.sendMessage(info.agent,
          `REMINDER: You have a pending task (${taskId}). If you have completed it, please write a result file to .ce-hub/results/. ` +
          `Example: cat > .ce-hub/results/result_${info.agent}_$(date +%s).json << 'EOF'\n` +
          `{"from":"${info.agent}","task_id":"${taskId}","status":"done","summary":"what you did","output_files":[]}\nEOF`
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
    if (this.nudgeTimer) clearInterval(this.nudgeTimer);
    if (this.taskTimeoutTimer) clearInterval(this.taskTimeoutTimer);
    for (const w of this.watchers) w.close();
    this.watchers = [];
  }
}
