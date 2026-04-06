import EventEmitter2pkg from 'eventemitter2';
const { EventEmitter2 } = EventEmitter2pkg as any;
import PQueue from 'p-queue';
import pRetry from 'p-retry';
import toposort from 'toposort';
import { writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { StateStore } from './state-store.js';
import type { Task, CreateTaskInput } from './types.js';

export class TaskEngine {
  private store: StateStore;
  public emitter: EventEmitter2;
  private queues: Record<string, PQueue>;

  constructor(store: StateStore) {
    this.store = store;
    this.emitter = new EventEmitter2({ wildcard: true });
    this.queues = {
      opus: new PQueue({ concurrency: 3 }),
      flash: new PQueue({ concurrency: 3 }),
      ollama: new PQueue({ concurrency: 1 }),
    };
  }

  validateDag(taskId: string, dependsOn: string[]): void {
    if (dependsOn.length === 0) return;
    const edges: [string, string][] = [];
    for (const t of this.store.listTasks()) for (const dep of t.depends_on) edges.push([dep, t.id]);
    for (const dep of dependsOn) edges.push([dep, taskId]);
    try { toposort(edges); } catch (err) { throw new Error(`Dependency cycle: ${err}`); }
  }

  async createTask(input: CreateTaskInput): Promise<Task> {
    const task = this.store.createTask(input);
    try { this.validateDag(task.id, task.depends_on); } catch (err) {
      this.store.updateTask(task.id, { status: 'failed', error: String(err) }); throw err;
    }
    this.store.createEvent({ type: `task.created`, source: task.from_agent, target: task.to_agent, payload: { taskId: task.id, title: task.title } });
    this.emitter.emit(`task.${task.id}.created`, task);
    if (task.depends_on.length === 0) await this.queueTask(task.id);
    return this.store.getTask(task.id)!;
  }

  private async queueTask(taskId: string): Promise<void> {
    const task = this.store.getTask(taskId);
    if (!task || task.status !== 'pending') return;
    this.store.updateTask(taskId, { status: 'queued' });
    const tier = task.model_tier in this.queues ? task.model_tier : 'opus';
    this.queues[tier].add(() => this.runTask(taskId)).catch(e => console.error(`[task-engine] queue error ${taskId}:`, e));
  }

  private async runTask(taskId: string): Promise<void> {
    const task = this.store.getTask(taskId);
    if (!task || (task.status !== 'queued' && task.status !== 'pending')) return;
    this.store.updateTask(taskId, { status: 'running', started_at: Date.now() });
    this.emitter.emit(`task.${taskId}.started`, task);
    try {
      const result = await pRetry(() => this.executeTask(taskId), {
        retries: task.max_retries,
        onFailedAttempt: (e) => { console.warn(`[task-engine] ${taskId} attempt ${e.attemptNumber} failed`); this.store.incrementTaskRetry(taskId); },
      });
      // Task dispatched to agent — mark as in_progress, not done
      // FileWatcher.handleResult() will mark it done when agent writes a result file
      this.store.updateTask(taskId, { status: 'in_progress', result });
      this.emitter.emit(`task.${taskId}.dispatched`, result);
      // Downstream triggering happens in FileWatcher.handleResult()
    } catch (err) {
      const t = this.store.getTask(taskId)!;
      const status = t.retry_count >= t.max_retries ? 'dead_letter' : 'failed';
      this.store.updateTask(taskId, { status, error: String(err), completed_at: Date.now() });
      this.emitter.emit(`task.${taskId}.failed`, { error: String(err), status });
    }
  }

  // Execute task by writing dispatch file → FileWatcher picks it up → agent runs it
  // Returns immediately after dispatch; actual completion tracked via result files
  private async executeTask(taskId: string): Promise<Record<string, unknown>> {
    const task = this.store.getTask(taskId);
    if (!task) throw new Error(`Task ${taskId} not found`);

    const ceHubDir = join(process.env.CE_HUB_CWD || process.cwd(), '.ce-hub');
    const dispatchDir = join(ceHubDir, 'dispatch');
    if (!existsSync(dispatchDir)) mkdirSync(dispatchDir, { recursive: true });

    const dispatchFile = join(dispatchDir, `task_${taskId}.json`);
    writeFileSync(dispatchFile, JSON.stringify({
      id: taskId,
      from: task.from_agent || 'task-engine',
      to: task.to_agent,
      task: task.title,
      context: task.payload?.context || '',
      priority: task.priority,
      created_at: new Date().toISOString(),
    }, null, 2));

    console.log(`[TaskEngine] dispatched ${taskId} → ${task.to_agent} via file protocol`);

    // Don't wait for completion — FileWatcher handles result files
    // Mark as in_progress (not done) so the task stays tracked
    return { dispatched: true, dispatchedAt: new Date().toISOString(), agent: task.to_agent };
  }

  async triggerDownstream(completedId: string): Promise<void> {
    for (const t of this.store.getTasksWaitingOnDep(completedId)) {
      if (t.depends_on.every(d => this.store.getTask(d)?.status === 'done')) await this.queueTask(t.id);
    }
  }

  async retryTask(taskId: string): Promise<Task | null> {
    const t = this.store.getTask(taskId);
    if (!t || (t.status !== 'failed' && t.status !== 'dead_letter')) return null;
    this.store.updateTask(taskId, { status: 'pending', error: undefined });
    await this.queueTask(taskId);
    return this.store.getTask(taskId);
  }

  cancelTask(taskId: string): Task | null {
    const t = this.store.getTask(taskId);
    if (!t || (t.status !== 'pending' && t.status !== 'queued')) return null;
    return this.store.updateTask(taskId, { status: 'failed', error: 'Cancelled' });
  }

  getQueueStats() {
    return Object.fromEntries(Object.entries(this.queues).map(([k, q]) => [k, { size: q.size, pending: q.pending }]));
  }
}
