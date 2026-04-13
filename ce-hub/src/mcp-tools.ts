/**
 * MCP Tools — 12 tool implementations
 *
 * Tools are organized by category:
 *   dispatch: dispatch_task, check_inbox, submit_result, get_task_status
 *   agent:    list_agents, get_agent_memory
 *   pipeline: report_pipeline_heartbeat, get_pipeline_status, preflight_check,
 *             get_next_book, acquire_resource_slot, release_resource_slot
 *   knowledge: query_wiki, get_project_context
 *   cost:     report_cost
 *   extract:  extract_chunk, classify_chunk, batch_extract
 *
 * All tools directly call StateStore/TaskEngine/MemoryManager — no HTTP overhead.
 */

import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { v4 as uuidv4 } from 'uuid';
import type { StateStore } from './state-store.js';
import type { TaskEngine } from './task-engine.js';
import type { MemoryManager } from './memory-manager.js';
import type { CostTracker } from './cost-tracker.js';
import { ResourceLock } from './resource-lock.js';
import { BookDispatcher } from './book-dispatcher.js';
import { antigravityClient } from './antigravity-client.js';
import Database from 'better-sqlite3';

function getCwd(): string { return process.env.CE_HUB_CWD || process.cwd(); }

// ── Tool context (injected by mcp-server.ts) ──────────────────────────────────

export interface McpToolContext {
  store: StateStore;
  engine: TaskEngine;
  memory: MemoryManager;
  costTracker: CostTracker;
  db: Database.Database;
  resourceLock: ResourceLock;
  bookDispatcher: BookDispatcher;
}

// ── Tool result type ──────────────────────────────────────────────────────────

export type ToolResult = {
  content: Array<{ type: 'text'; text: string }>;
  isError?: boolean;
};

function ok(data: unknown): ToolResult {
  return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
}

function err(message: string): ToolResult {
  return { content: [{ type: 'text', text: JSON.stringify({ error: message }) }], isError: true };
}

// ═══════════════════════════════════════════════════════════════════════════════
// DISPATCH TOOLS
// ═══════════════════════════════════════════════════════════════════════════════

export async function dispatch_task(ctx: McpToolContext, params: {
  to: string;
  task: string;
  priority?: number;
  context?: string;
  expected_output?: string;
  model_tier?: 'opus' | 'flash' | 'ollama';
}): Promise<ToolResult> {
  try {
    const task = await ctx.engine.createTask({
      title: params.task,
      from_agent: 'mcp-client',
      to_agent: params.to,
      priority: params.priority ?? 1,
      model_tier: params.model_tier ?? 'opus',
      payload: {
        context: params.context ?? '',
        expected_output: params.expected_output ?? '',
      },
    });
    return ok({ task_id: task.id, status: task.status, title: task.title });
  } catch (e) {
    return err(String(e));
  }
}

export async function check_inbox(ctx: McpToolContext, params: {
  agent_name: string;
  limit?: number;
}): Promise<ToolResult> {
  try {
    const tasks = ctx.store.listTasks({ to_agent: params.agent_name, status: 'pending' });
    const limited = tasks.slice(0, params.limit ?? 10);
    return ok(limited.map(t => ({
      task_id: t.id,
      from: t.from_agent,
      title: t.title,
      priority: t.priority,
      payload: t.payload,
      created_at: new Date(t.created_at).toISOString(),
    })));
  } catch (e) {
    return err(String(e));
  }
}

export async function submit_result(ctx: McpToolContext, params: {
  task_id: string;
  status: 'done' | 'failed' | 'partial';
  content?: string;
  output_files?: string[];
  summary?: string;
}): Promise<ToolResult> {
  try {
    const updated = ctx.store.updateTask(params.task_id, {
      status: params.status === 'done' ? 'done' : params.status === 'partial' ? 'in_progress' : 'failed',
      result: { content: params.content, output_files: params.output_files ?? [], summary: params.summary ?? '' },
      completed_at: params.status !== 'partial' ? Date.now() : undefined,
    });
    if (!updated) return err(`Task ${params.task_id} not found`);
    return ok({ ok: true, task_id: params.task_id, status: updated.status });
  } catch (e) {
    return err(String(e));
  }
}

export async function get_task_status(ctx: McpToolContext, params: {
  task_id: string;
}): Promise<ToolResult> {
  try {
    const task = ctx.store.getTask(params.task_id);
    if (!task) return err(`Task ${params.task_id} not found`);
    return ok({
      task_id: task.id, title: task.title, status: task.status,
      from: task.from_agent, to: task.to_agent,
      result: task.result, error: task.error,
      created_at: new Date(task.created_at).toISOString(),
      completed_at: task.completed_at ? new Date(task.completed_at).toISOString() : null,
    });
  } catch (e) {
    return err(String(e));
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// AGENT TOOLS
// ═══════════════════════════════════════════════════════════════════════════════

export async function list_agents(_ctx: McpToolContext, _params: Record<string, never>): Promise<ToolResult> {
  try {
    const agentsDir = join(getCwd(), '.claude', 'agents');
    if (!existsSync(agentsDir)) return ok([]);

    const agents = readdirSync(agentsDir)
      .filter(f => f.endsWith('.md'))
      .map(f => {
        const name = f.replace('.md', '');
        const content = readFileSync(join(agentsDir, f), 'utf-8');
        const descMatch = content.match(/description:\s*(.+)/);
        const modelMatch = content.match(/model:\s*(.+)/);
        return {
          name,
          description: descMatch?.[1]?.trim() ?? '',
          model: modelMatch?.[1]?.trim() ?? 'unknown',
        };
      });

    return ok(agents);
  } catch (e) {
    return err(String(e));
  }
}

export async function get_agent_memory(ctx: McpToolContext, params: {
  agent_name: string;
}): Promise<ToolResult> {
  try {
    const memories = ctx.memory.getMemory(params.agent_name);
    return ok({ agent: params.agent_name, memories });
  } catch (e) {
    return err(String(e));
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// PIPELINE TOOLS
// ═══════════════════════════════════════════════════════════════════════════════

export async function report_pipeline_heartbeat(ctx: McpToolContext, params: {
  pipeline_id: string;
  book_id: string;
  step: number;
  progress_pct: number;
  current_chunk?: string;
  eta_minutes?: number;
  track?: string;
}): Promise<ToolResult> {
  try {
    const now = Date.now();
    // Upsert pipeline_runs
    const existing = ctx.db.prepare('SELECT id FROM pipeline_runs WHERE id = ?').get(params.pipeline_id);
    if (existing) {
      ctx.db.prepare(
        `UPDATE pipeline_runs SET step=?, progress_pct=?, current_chunk=?, eta_minutes=?, last_heartbeat=?, status='running' WHERE id=?`
      ).run(params.step, params.progress_pct, params.current_chunk ?? null, params.eta_minutes ?? null, now, params.pipeline_id);
    } else {
      ctx.db.prepare(
        `INSERT INTO pipeline_runs (id, book_id, track, step, progress_pct, current_chunk, eta_minutes, status, started_at, last_heartbeat)
         VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)`
      ).run(params.pipeline_id, params.book_id, params.track ?? 'A', params.step, params.progress_pct, params.current_chunk ?? null, params.eta_minutes ?? null, now, now);
    }
    return ok({ ok: true, pipeline_id: params.pipeline_id, recorded_at: new Date(now).toISOString() });
  } catch (e) {
    return err(String(e));
  }
}

export async function get_pipeline_status(ctx: McpToolContext, params: {
  pipeline_id?: string;
}): Promise<ToolResult> {
  try {
    const staleThreshold = Date.now() - 5 * 60 * 1000; // 5 min without heartbeat = stale

    let rows: Record<string, unknown>[];
    if (params.pipeline_id) {
      rows = ctx.db.prepare('SELECT * FROM pipeline_runs WHERE id = ?').all(params.pipeline_id) as Record<string, unknown>[];
    } else {
      rows = ctx.db.prepare(`SELECT * FROM pipeline_runs WHERE status IN ('running', 'failed') ORDER BY last_heartbeat DESC LIMIT 20`).all() as Record<string, unknown>[];
    }

    return ok(rows.map(r => ({
      pipeline_id: r.id,
      book_id: r.book_id,
      track: r.track,
      step: r.step,
      progress_pct: r.progress_pct,
      current_chunk: r.current_chunk,
      eta_minutes: r.eta_minutes,
      status: (r.last_heartbeat as number) < staleThreshold && r.status === 'running' ? 'stale' : r.status,
      started_at: r.started_at ? new Date(r.started_at as number).toISOString() : null,
      last_heartbeat: r.last_heartbeat ? new Date(r.last_heartbeat as number).toISOString() : null,
    })));
  } catch (e) {
    return err(String(e));
  }
}

export async function preflight_check(ctx: McpToolContext, params: {
  book_id: string;
  steps?: number[];
}): Promise<ToolResult> {
  try {
    const result = await ctx.bookDispatcher.preflight(params.book_id, params.steps ?? [1, 2, 3, 4]);
    return ok(result);
  } catch (e) {
    return err(String(e));
  }
}

export async function get_next_book(ctx: McpToolContext, params: {
  track?: string;
  step?: 'prep' | 'extract' | 'qc';
  pipeline_id: string;
}): Promise<ToolResult> {
  try {
    const book = ctx.bookDispatcher.getNextBook({
      track: params.track,
      step: params.step ?? 'prep',
      assignedTo: params.pipeline_id,
    });
    if (!book) return ok({ book: null, message: 'No books available in queue' });
    return ok({ book });
  } catch (e) {
    return err(String(e));
  }
}

export async function acquire_resource_slot(ctx: McpToolContext, params: {
  resource: string;
  holder: string;
  ttl_ms?: number;
}): Promise<ToolResult> {
  try {
    const result = ctx.resourceLock.acquire(params.resource, params.holder, params.ttl_ms);
    return ok(result);
  } catch (e) {
    return err(String(e));
  }
}

export async function release_resource_slot(ctx: McpToolContext, params: {
  resource: string;
  slot_id: string;
}): Promise<ToolResult> {
  try {
    const released = ctx.resourceLock.release(params.resource, params.slot_id);
    return ok({ ok: released, slot_id: params.slot_id });
  } catch (e) {
    return err(String(e));
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// KNOWLEDGE TOOLS
// ═══════════════════════════════════════════════════════════════════════════════

export async function query_wiki(_ctx: McpToolContext, params: {
  page_path: string;
}): Promise<ToolResult> {
  try {
    const cwd = getCwd();
    const wikiDir = join(cwd, 'wiki');

    // Normalize path
    let p = params.page_path;
    if (!p.startsWith('/')) p = join(wikiDir, p);
    if (!p.endsWith('.md')) p += '.md';
    // Prevent path traversal
    if (!p.startsWith(wikiDir)) return err('Path outside wiki directory');

    if (!existsSync(p)) {
      // List available pages
      const pages = readdirSync(wikiDir).filter(f => f.endsWith('.md'));
      return err(`Wiki page not found: ${params.page_path}. Available: ${pages.join(', ')}`);
    }

    const content = readFileSync(p, 'utf-8');
    return ok({ path: params.page_path, content: content.slice(0, 8000), truncated: content.length > 8000 });
  } catch (e) {
    return err(String(e));
  }
}

export async function get_project_context(_ctx: McpToolContext, _params: Record<string, never>): Promise<ToolResult> {
  try {
    const cwd = getCwd();
    const sections: Record<string, string> = {};

    // STATUS.md (first 3000 chars)
    const statusPath = join(cwd, 'STATUS.md');
    if (existsSync(statusPath)) {
      sections.status = readFileSync(statusPath, 'utf-8').slice(0, 3000);
    }

    // wiki/STATUS.md
    const wikiStatusPath = join(cwd, 'wiki', 'STATUS.md');
    if (existsSync(wikiStatusPath)) {
      sections.wiki_status = readFileSync(wikiStatusPath, 'utf-8').slice(0, 3000);
    }

    // Recent decisions from wiki/DECISIONS.md
    const decisionsPath = join(cwd, 'wiki', 'DECISIONS.md');
    if (existsSync(decisionsPath)) {
      sections.recent_decisions = readFileSync(decisionsPath, 'utf-8').slice(-2000);
    }

    return ok({
      cwd,
      sections,
      generated_at: new Date().toISOString(),
    });
  } catch (e) {
    return err(String(e));
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// COST TOOL
// ═══════════════════════════════════════════════════════════════════════════════

export async function report_cost(ctx: McpToolContext, params: {
  agent: string;
  model: string;
  tokens_in?: number;
  tokens_out?: number;
  task_id?: string;
}): Promise<ToolResult> {
  try {
    ctx.costTracker.log({ agent: params.agent, model: params.model, input_tokens: params.tokens_in ?? 0, output_tokens: params.tokens_out ?? 0, cost_usd: 0, task_id: params.task_id });
    return ok({ ok: true });
  } catch (e) {
    return err(String(e));
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// EXTRACT TOOLS
// ═══════════════════════════════════════════════════════════════════════════════

export async function extract_chunk(_ctx: McpToolContext, params: {
  chunk_text: string;
  skill: string;
  model?: 'pro' | 'flash' | 'lingya';
  book_id?: string;
}): Promise<ToolResult> {
  try {
    const result = await antigravityClient.extractChunk({
      chunkText: params.chunk_text,
      skill: params.skill,
      model: params.model ?? 'pro',
      bookId: params.book_id,
    });
    return ok(result);
  } catch (e) {
    return err(String(e));
  }
}

export async function classify_chunk(_ctx: McpToolContext, params: {
  chunk_text: string;
}): Promise<ToolResult> {
  try {
    const result = await antigravityClient.classifyChunk(params.chunk_text);
    return ok(result);
  } catch (e) {
    return err(String(e));
  }
}

export async function batch_extract(_ctx: McpToolContext, params: {
  chunks: Array<{ id: string; text: string }>;
  skill: string;
  model?: 'pro' | 'flash' | 'lingya';
  book_id?: string;
  concurrency?: number;
}): Promise<ToolResult> {
  try {
    const concurrency = Math.min(params.concurrency ?? 3, 5); // max 5
    const results: Array<{ id: string; result: unknown }> = [];

    // Process in batches
    for (let i = 0; i < params.chunks.length; i += concurrency) {
      const batch = params.chunks.slice(i, i + concurrency);
      const batchResults = await Promise.all(
        batch.map(async chunk => {
          try {
            const r = await antigravityClient.extractChunk({
              chunkText: chunk.text,
              skill: params.skill,
              model: params.model ?? 'pro',
              bookId: params.book_id,
            });
            return { id: chunk.id, result: r };
          } catch (e) {
            return { id: chunk.id, result: { error: String(e), has_formula: false } };
          }
        })
      );
      results.push(...batchResults);
    }

    const hasFormula = results.filter(r => (r.result as Record<string, unknown>).has_formula).length;
    return ok({
      total: results.length,
      has_formula: hasFormula,
      no_formula: results.length - hasFormula,
      results,
    });
  } catch (e) {
    return err(String(e));
  }
}
