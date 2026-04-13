/**
 * Standalone MCP stdio server entry point
 *
 * Used by Antigravity / Claude Code via mcp_config.json:
 *   {
 *     "mcpServers": {
 *       "culinary-hub": {
 *         "command": "node",
 *         "args": ["/Users/jeff/culinary-mind/ce-hub/dist/mcp-stdio-main.js"],
 *         "transport": "stdio"
 *       }
 *     }
 *   }
 *
 * Or with tsx in dev:
 *   npx tsx src/mcp-stdio-main.ts
 */

// Load .env
import { readFileSync, existsSync, mkdirSync } from 'node:fs';
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
import { MemoryManager } from './memory-manager.js';
import { CostTracker } from './cost-tracker.js';
import { ResourceLock } from './resource-lock.js';
import { BookDispatcher } from './book-dispatcher.js';
import { startMcpStdio } from './mcp-server.js';
import type { McpToolContext } from './mcp-tools.js';

const CWD = process.env.CE_HUB_CWD || process.cwd();
const DB_PATH = process.env.CE_HUB_DB_PATH || join(CWD, '.ce-hub', 'ce-hub.db');

// Ensure .ce-hub exists
for (const dir of ['dispatch', 'inbox', 'results', 'memory']) {
  const p = join(CWD, '.ce-hub', dir);
  if (!existsSync(p)) mkdirSync(p, { recursive: true });
}

const store = new StateStore(DB_PATH);
const engine = new TaskEngine(store);
const memory = new MemoryManager();
memory.initialize();
const costTracker = new CostTracker(store);
costTracker.initialize();

const db = (store as any).db;
const resourceLock = new ResourceLock(db);
const bookDispatcher = new BookDispatcher(db);

const ctx: McpToolContext = { store, engine, memory, costTracker, db, resourceLock, bookDispatcher };

// Start stdio transport
startMcpStdio(ctx).catch(e => {
  process.stderr.write(`[mcp-stdio] Fatal: ${e}\n`);
  process.exit(1);
});
