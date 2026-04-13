/**
 * ce-hub MCP Server
 *
 * Registers all MCP tools and starts both transport modes:
 *   - stdio: for Antigravity / Claude Code direct integration
 *   - SSE:   for remote clients (Mac Mini, OpenClaw)
 *
 * Started in-process from index.ts — shares same StateStore/TaskEngine/etc.
 *
 * stdio MCP endpoint:   node dist/mcp-server.js  (standalone stdio)
 * SSE MCP endpoint:     http://localhost:8750/mcp/sse
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import type { FastifyInstance } from 'fastify';
import type { McpToolContext } from './mcp-tools.js';
import * as tools from './mcp-tools.js';

// ── Tool definitions for MCP protocol ────────────────────────────────────────

const TOOL_DEFINITIONS = [
  // ── Dispatch ──────────────────────────────────────────────────────────────
  {
    name: 'dispatch_task',
    description: 'Dispatch a task to a specific agent. Returns task_id.',
    inputSchema: {
      type: 'object',
      properties: {
        to: { type: 'string', description: 'Target agent name (e.g. "coder", "architect")' },
        task: { type: 'string', description: 'Task title/description' },
        priority: { type: 'number', description: '0=P0 critical, 1=P1 normal, 2=P2 low' },
        context: { type: 'string', description: 'Background context for the agent' },
        expected_output: { type: 'string', description: 'What the agent should produce' },
        model_tier: { type: 'string', enum: ['opus', 'flash', 'ollama'] },
      },
      required: ['to', 'task'],
    },
  },
  {
    name: 'check_inbox',
    description: 'Check pending tasks for an agent.',
    inputSchema: {
      type: 'object',
      properties: {
        agent_name: { type: 'string', description: 'Agent name to check inbox for' },
        limit: { type: 'number', description: 'Max tasks to return (default 10)' },
      },
      required: ['agent_name'],
    },
  },
  {
    name: 'submit_result',
    description: 'Submit result for a completed task.',
    inputSchema: {
      type: 'object',
      properties: {
        task_id: { type: 'string' },
        status: { type: 'string', enum: ['done', 'failed', 'partial'] },
        content: { type: 'string', description: 'Result content or summary' },
        output_files: { type: 'array', items: { type: 'string' }, description: 'Paths to output files' },
        summary: { type: 'string', description: 'One-line summary for cc-lead' },
      },
      required: ['task_id', 'status'],
    },
  },
  {
    name: 'get_task_status',
    description: 'Get current status of a task by ID.',
    inputSchema: {
      type: 'object',
      properties: {
        task_id: { type: 'string' },
      },
      required: ['task_id'],
    },
  },

  // ── Agent ─────────────────────────────────────────────────────────────────
  {
    name: 'list_agents',
    description: 'List all available agents with name, description, and model.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'get_agent_memory',
    description: 'Get memory files for a specific agent.',
    inputSchema: {
      type: 'object',
      properties: {
        agent_name: { type: 'string' },
      },
      required: ['agent_name'],
    },
  },

  // ── Pipeline ──────────────────────────────────────────────────────────────
  {
    name: 'report_pipeline_heartbeat',
    description: 'Report progress heartbeat for a running pipeline. Call every ~10 chunks.',
    inputSchema: {
      type: 'object',
      properties: {
        pipeline_id: { type: 'string', description: 'Unique pipeline run ID (e.g. "van_boekel_extract_001")' },
        book_id: { type: 'string', description: 'Book being processed' },
        step: { type: 'number', description: 'Pipeline step number (1-5)' },
        progress_pct: { type: 'number', description: 'Progress 0-100' },
        current_chunk: { type: 'string', description: 'Current chunk title/ID being processed' },
        eta_minutes: { type: 'number', description: 'Estimated minutes remaining' },
        track: { type: 'string', description: 'Track A or B' },
      },
      required: ['pipeline_id', 'book_id', 'step', 'progress_pct'],
    },
  },
  {
    name: 'get_pipeline_status',
    description: 'Get current status of all running (or a specific) pipeline.',
    inputSchema: {
      type: 'object',
      properties: {
        pipeline_id: { type: 'string', description: 'Optional: specific pipeline ID' },
      },
    },
  },
  {
    name: 'preflight_check',
    description: 'Run preflight checks before starting a pipeline for a book.',
    inputSchema: {
      type: 'object',
      properties: {
        book_id: { type: 'string' },
        steps: { type: 'array', items: { type: 'number' }, description: 'Steps to check for (e.g. [1,2,3,4])' },
      },
      required: ['book_id'],
    },
  },
  {
    name: 'get_next_book',
    description: 'Get and claim the next available book from the processing queue.',
    inputSchema: {
      type: 'object',
      properties: {
        track: { type: 'string', description: 'Filter by track: "A" or "B"' },
        step: { type: 'string', enum: ['prep', 'extract', 'qc'], description: 'Which step to assign' },
        pipeline_id: { type: 'string', description: 'Unique ID of the claiming pipeline instance' },
      },
      required: ['pipeline_id'],
    },
  },
  {
    name: 'acquire_resource_slot',
    description: 'Acquire a concurrency slot for ollama/gemini_flash/gemini_pro/lingya_opus.',
    inputSchema: {
      type: 'object',
      properties: {
        resource: { type: 'string', enum: ['ollama', 'gemini_flash', 'gemini_pro', 'lingya_opus'] },
        holder: { type: 'string', description: 'Who is acquiring (pipeline_id or agent_name)' },
        ttl_ms: { type: 'number', description: 'TTL in milliseconds (default varies by resource)' },
      },
      required: ['resource', 'holder'],
    },
  },
  {
    name: 'release_resource_slot',
    description: 'Release a previously acquired resource slot.',
    inputSchema: {
      type: 'object',
      properties: {
        resource: { type: 'string' },
        slot_id: { type: 'string', description: 'slot_id returned by acquire_resource_slot' },
      },
      required: ['resource', 'slot_id'],
    },
  },

  // ── Knowledge ─────────────────────────────────────────────────────────────
  {
    name: 'query_wiki',
    description: 'Read a wiki page by path (relative to wiki/).',
    inputSchema: {
      type: 'object',
      properties: {
        page_path: { type: 'string', description: 'e.g. "STATUS" or "DECISIONS" (without .md)' },
      },
      required: ['page_path'],
    },
  },
  {
    name: 'get_project_context',
    description: 'Get compiled project context: STATUS.md + recent decisions + active pipelines.',
    inputSchema: { type: 'object', properties: {} },
  },

  // ── Cost ──────────────────────────────────────────────────────────────────
  {
    name: 'report_cost',
    description: 'Log API cost for an agent/model call.',
    inputSchema: {
      type: 'object',
      properties: {
        agent: { type: 'string' },
        model: { type: 'string', description: 'e.g. "gemini-2.5-pro", "lingya_opus"' },
        tokens_in: { type: 'number' },
        tokens_out: { type: 'number' },
        task_id: { type: 'string' },
      },
      required: ['agent', 'model'],
    },
  },

  // ── Extract ───────────────────────────────────────────────────────────────
  {
    name: 'extract_chunk',
    description: 'Extract formula/parameters from a text chunk using Antigravity Skill A or B.',
    inputSchema: {
      type: 'object',
      properties: {
        chunk_text: { type: 'string', description: 'The text chunk to extract from' },
        skill: { type: 'string', description: '"parameter-extractor-a" (engineering) or "parameter-extractor-b" (cookbook)' },
        model: { type: 'string', enum: ['pro', 'flash', 'lingya'] },
        book_id: { type: 'string' },
      },
      required: ['chunk_text', 'skill'],
    },
  },
  {
    name: 'classify_chunk',
    description: 'Classify a text chunk: science/recipe/narrative/table/reference.',
    inputSchema: {
      type: 'object',
      properties: {
        chunk_text: { type: 'string' },
      },
      required: ['chunk_text'],
    },
  },
  {
    name: 'batch_extract',
    description: 'Extract from multiple chunks in parallel (max 5 concurrent).',
    inputSchema: {
      type: 'object',
      properties: {
        chunks: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              text: { type: 'string' },
            },
            required: ['id', 'text'],
          },
        },
        skill: { type: 'string' },
        model: { type: 'string', enum: ['pro', 'flash', 'lingya'] },
        book_id: { type: 'string' },
        concurrency: { type: 'number', description: 'Max concurrent calls (1-5, default 3)' },
      },
      required: ['chunks', 'skill'],
    },
  },
] as const;

// ── Tool router ───────────────────────────────────────────────────────────────

type AnyParams = Record<string, unknown>;

async function callTool(name: string, params: AnyParams, ctx: McpToolContext): Promise<tools.ToolResult> {
  switch (name) {
    // Dispatch
    case 'dispatch_task':         return tools.dispatch_task(ctx, params as Parameters<typeof tools.dispatch_task>[1]);
    case 'check_inbox':           return tools.check_inbox(ctx, params as Parameters<typeof tools.check_inbox>[1]);
    case 'submit_result':         return tools.submit_result(ctx, params as Parameters<typeof tools.submit_result>[1]);
    case 'get_task_status':       return tools.get_task_status(ctx, params as Parameters<typeof tools.get_task_status>[1]);
    // Agent
    case 'list_agents':           return tools.list_agents(ctx, {} as never);
    case 'get_agent_memory':      return tools.get_agent_memory(ctx, params as Parameters<typeof tools.get_agent_memory>[1]);
    // Pipeline
    case 'report_pipeline_heartbeat': return tools.report_pipeline_heartbeat(ctx, params as Parameters<typeof tools.report_pipeline_heartbeat>[1]);
    case 'get_pipeline_status':   return tools.get_pipeline_status(ctx, params as Parameters<typeof tools.get_pipeline_status>[1]);
    case 'preflight_check':       return tools.preflight_check(ctx, params as Parameters<typeof tools.preflight_check>[1]);
    case 'get_next_book':         return tools.get_next_book(ctx, params as Parameters<typeof tools.get_next_book>[1]);
    case 'acquire_resource_slot': return tools.acquire_resource_slot(ctx, params as Parameters<typeof tools.acquire_resource_slot>[1]);
    case 'release_resource_slot': return tools.release_resource_slot(ctx, params as Parameters<typeof tools.release_resource_slot>[1]);
    // Knowledge
    case 'query_wiki':            return tools.query_wiki(ctx, params as Parameters<typeof tools.query_wiki>[1]);
    case 'get_project_context':   return tools.get_project_context(ctx, {} as never);
    // Cost
    case 'report_cost':           return tools.report_cost(ctx, params as Parameters<typeof tools.report_cost>[1]);
    // Extract
    case 'extract_chunk':         return tools.extract_chunk(ctx, params as Parameters<typeof tools.extract_chunk>[1]);
    case 'classify_chunk':        return tools.classify_chunk(ctx, params as Parameters<typeof tools.classify_chunk>[1]);
    case 'batch_extract':         return tools.batch_extract(ctx, params as Parameters<typeof tools.batch_extract>[1]);
    default: return { content: [{ type: 'text', text: JSON.stringify({ error: `Unknown tool: ${name}` }) }], isError: true };
  }
}

// ── MCP Server factory ────────────────────────────────────────────────────────

function createMcpServer(ctx: McpToolContext): Server {
  const server = new Server(
    { name: 'culinary-hub', version: '1.0.0' },
    { capabilities: { tools: {} } },
  );

  // List tools
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOL_DEFINITIONS.map(t => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
    })),
  }));

  // Call tool
  server.setRequestHandler(CallToolRequestSchema, async req => {
    const { name, arguments: params = {} } = req.params;
    console.log(`[mcp-server] tool call: ${name}`);
    const result = await callTool(name, params as AnyParams, ctx);
    return result;
  });

  return server;
}

// ── Stdio mode (standalone / Antigravity integration) ─────────────────────────

export async function startMcpStdio(ctx: McpToolContext): Promise<void> {
  const server = createMcpServer(ctx);
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('[mcp-server] stdio transport connected'); // stderr so it doesn't pollute MCP protocol
}

// ── SSE mode (embedded in Fastify — for remote clients) ───────────────────────

export function registerMcpSse(fastify: FastifyInstance, ctx: McpToolContext): void {
  // Map of session_id → transport
  const transports = new Map<string, SSEServerTransport>();

  // SSE stream endpoint
  fastify.get('/mcp/sse', async (req, reply) => {
    const server = createMcpServer(ctx);
    const transport = new SSEServerTransport('/mcp/message', reply.raw);

    // Register by session ID (from query or generated)
    const sessionId = (req.query as Record<string, string>).sessionId ?? `${Date.now()}`;
    transports.set(sessionId, transport);

    reply.raw.on('close', () => {
      transports.delete(sessionId);
      console.log(`[mcp-server] SSE client disconnected: ${sessionId}`);
    });

    await server.connect(transport);
    console.log(`[mcp-server] SSE client connected: ${sessionId}`);
    // SSE stays open — don't return
    await new Promise(() => {}); // keep alive
  });

  // POST message endpoint (MCP over SSE requires this)
  fastify.post('/mcp/message', async (req, reply) => {
    const sessionId = (req.query as Record<string, string>).sessionId;
    const transport = sessionId ? transports.get(sessionId) : undefined;
    if (!transport) {
      reply.code(404).send({ error: 'Session not found' });
      return;
    }
    await transport.handlePostMessage(req.raw, reply.raw, req.body);
  });

  console.log('[mcp-server] SSE endpoints registered: GET /mcp/sse, POST /mcp/message');
}
