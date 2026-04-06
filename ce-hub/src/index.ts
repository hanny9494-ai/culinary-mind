// Load .env if present
import { readFileSync, existsSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
const envPath = new URL('../.env', import.meta.url).pathname;
if (existsSync(envPath)) {
  for (const line of readFileSync(envPath, 'utf-8').split('\n')) {
    const m = line.match(/^(\w+)=(.+)$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].trim();
  }
}

import { StateStore } from './state-store.js';
import { TaskEngine } from './task-engine.js';
import { TmuxManager } from './tmux-manager.js';
import { FileWatcher } from './file-watcher.js';
import { MemoryManager } from './memory-manager.js';
import { QualityGate } from './quality-gate.js';
import { CostTracker } from './cost-tracker.js';
import { Scheduler } from './scheduler.js';
import { buildApp } from './api.js';
import { ResumeBuilder } from './resume-builder.js';

const CWD = process.env.CE_HUB_CWD || process.cwd();
const DB_PATH = process.env.CE_HUB_DB_PATH || join(CWD, '.ce-hub', 'ce-hub.db');
const PORT = parseInt(process.env.CE_HUB_PORT || '8750');

async function main() {
  console.log('[ce-hub] Starting v2...');
  console.log(`[ce-hub] CWD: ${CWD}`);
  console.log(`[ce-hub] DB: ${DB_PATH}`);

  // Ensure .ce-hub directory structure
  for (const dir of ['dispatch', 'inbox', 'results', 'memory']) {
    const p = join(CWD, '.ce-hub', dir);
    if (!existsSync(p)) mkdirSync(p, { recursive: true });
  }

  // Initialize all modules
  const store = new StateStore(DB_PATH);
  const tmux = new TmuxManager();
  tmux.initialize();
  const fileWatcher = new FileWatcher(tmux, store);
  const memory = new MemoryManager();
  memory.initialize();
  const qualityGate = new QualityGate();
  qualityGate.initialize();
  const costTracker = new CostTracker(store);
  costTracker.initialize();
  const engine = new TaskEngine(store);
  fileWatcher.setEngine(engine);

  // Scheduler: dispatch tasks to agents via file protocol
  const scheduler = new Scheduler();
  scheduler.initialize((agent, task) => {
    const dispatchDir = join(CWD, '.ce-hub', 'dispatch');
    writeFileSync(join(dispatchDir, `sched_${Date.now()}.json`), JSON.stringify({
      id: `sched_${Date.now()}`, from: 'scheduler', to: agent,
      task, priority: 2, created_at: new Date().toISOString(),
    }, null, 2));
  });

  // Start file watcher (bridge layer)
  fileWatcher.start();

  // Resume builder: auto-restart CC Lead with context if it crashes
  const resumeBuilder = new ResumeBuilder(store, tmux);
  resumeBuilder.startMonitoring();

  // Build REST API (for monitoring, not for agent communication)
  const app = await buildApp(store, engine, tmux, costTracker, memory, scheduler);

  // Graceful shutdown
  const shutdown = async (sig: string) => {
    console.log(`[ce-hub] ${sig}, shutting down...`);
    scheduler.stop();
    fileWatcher.stop();
    resumeBuilder.stop();
    // Don't kill tmux session — agents keep running
    await app.close();
    store.close();
    console.log('[ce-hub] daemon stopped. tmux session "cehub" still running.');
    process.exit(0);
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));

  await app.listen({ port: PORT, host: '127.0.0.1' });

  console.log(`[ce-hub] Daemon ready on http://localhost:${PORT}`);
  console.log(`[ce-hub] tmux attach -t cehub`);

  // Write status file
  const statusFile = join(CWD, '.ce-hub', 'status.json');
  const updateStatus = () => {
    writeFileSync(statusFile, JSON.stringify({
      uptime: process.uptime(),
      agents: tmux.listWindows(),
      tasks: { total: store.countTasks() },
      costs: costTracker.getAgentCosts(),
      schedules: scheduler.listSchedules().length,
      updated_at: new Date().toISOString(),
    }, null, 2));
  };
  setInterval(updateStatus, 30_000);
  updateStatus();
}

main().catch(e => { console.error('[ce-hub] Fatal:', e); process.exit(1); });
