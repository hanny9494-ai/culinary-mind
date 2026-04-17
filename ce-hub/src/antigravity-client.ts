/**
 * Antigravity Client — 全自动双向桥
 *
 * 通信架构：
 *   控制平面：HTTP POST http://localhost:5000/api/command  → send_command() 触发执行
 *   数据平面：MCP Filesystem 共享目录                     → queue/ + results/
 *   回调通道：WebSocket ws://localhost:9812               → 实时监听结果
 *
 * 文件协议：
 *   queue/{chunk_id}.md      — ce-hub 写入 chunk 文本
 *   results/{chunk_id}.json  — Antigravity 写入处理结果
 *   manifest.json            — 批次任务清单（断点续传）
 *
 * Fallback chain：
 *   Antigravity Pro → Antigravity Flash → Lingya Opus (直调 L0_API_ENDPOINT)
 *
 * IMPORTANT: Node.js fetch() 不使用 env 代理，trust_env=false 等价，
 *   绕过本机 127.0.0.1:7890。
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';

// ── 环境变量 ───────────────────────────────────────────────────────────────────

// Clear proxy env vars — bypass 127.0.0.1:7890
delete process.env.http_proxy;
delete process.env.https_proxy;
delete process.env.HTTP_PROXY;
delete process.env.HTTPS_PROXY;
delete process.env.all_proxy;
delete process.env.ALL_PROXY;

const ANTIGRAVITY_HTTP   = process.env.ANTIGRAVITY_API   || 'http://localhost:5000';
const ANTIGRAVITY_WS_URL = process.env.ANTIGRAVITY_WS    || 'ws://localhost:9812';
const LINGYA_ENDPOINT    = process.env.L0_API_ENDPOINT   || '';
const LINGYA_KEY         = process.env.L0_API_KEY        || '';

const BRIDGE_DIR = process.env.ANTIGRAVITY_BRIDGE_DIR
  || join(
      process.env.CE_HUB_CWD || join(process.cwd(), '..'),
      'raw', 'architect', 'gemini-bridge',
    );

const QUEUE_DIR    = join(BRIDGE_DIR, 'queue');
const RESULTS_DIR  = join(BRIDGE_DIR, 'results');
const MANIFEST_PATH = join(BRIDGE_DIR, 'manifest.json');

const SKILLS_DIR = process.env.CE_HUB_CWD
  ? join(process.env.CE_HUB_CWD, '.gemini', 'skills')
  : join(process.cwd(), '..', '.gemini', 'skills');

// Timeouts
const CHUNK_TIMEOUT_MS  = 120_000;
const POLL_INTERVAL_MS  = 5_000;

// ── Types ──────────────────────────────────────────────────────────────────────

export type SkillName =
  | 'parameter-extractor-a'
  | 'parameter-extractor-b'
  | 'ingredient-atom-extractor'
  | 'flavor-terminology-extractor'
  | string;

export type ModelPreference = 'pro' | 'flash' | 'lingya';

export interface ExtractResult {
  has_formula: boolean;
  formula_id?: string;
  formula_type?: string;
  formula_name?: string;
  sympy_expression?: string;
  reasoning?: string;
  symbols?: Record<string, unknown>;
  applicable_range?: Record<string, unknown>;
  raw_response?: string;
  model_used?: string;
  tokens_used?: number;
  [key: string]: unknown;
}

export interface ClassifyResult {
  chunk_type: 'science' | 'recipe' | 'narrative' | 'table' | 'reference' | 'unknown';
  confidence: number;
  reasoning?: string;
}

// Multi-label classification
export type ChunkLabel = 'science' | 'recipe' | 'ingredient' | 'sensory' | 'terminology' | 'narrative' | 'table' | 'reference';

export interface MultiLabelClassifyResult {
  types: ChunkLabel[];
  confidence: Partial<Record<ChunkLabel, number>>;
  reasoning?: string;
}

// manifest.json structure
interface Manifest {
  batch_id: string;
  skill: string;
  model: string;
  input_dir: string;
  output_dir: string;
  total_files: number;
  processed_files: number;
  status: 'pending' | 'processing' | 'done' | 'partial';
  created_at: string;
  updated_at: string;
  options: Record<string, unknown>;
}

// ── Skill loading ──────────────────────────────────────────────────────────────

const skillCache: Record<string, string> = {};

function loadSkill(skillName: SkillName): string {
  if (skillCache[skillName]) return skillCache[skillName];
  const paths = [
    join(SKILLS_DIR, `${skillName}.md`),
    join(SKILLS_DIR, `${skillName}`),
  ];
  for (const p of paths) {
    if (existsSync(p)) {
      skillCache[skillName] = readFileSync(p, 'utf-8');
      return skillCache[skillName];
    }
  }
  console.error(`[antigravity-client] Skill not found: ${skillName} (searched ${paths.join(', ')})`);
  return `You are a food science parameter extraction assistant. Extract structured data from the provided text.`;
}

// ── JSON extraction from LLM response ─────────────────────────────────────────

function extractJsonFromText(text: string): Record<string, unknown> | null {
  try { return JSON.parse(text.trim()); } catch { /* fall through */ }

  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced) {
    try { return JSON.parse(fenced[1].trim()); } catch { /* fall through */ }
  }

  const braceMatch = text.match(/\{[\s\S]*\}/);
  if (braceMatch) {
    try { return JSON.parse(braceMatch[0]); } catch { /* fall through */ }
  }

  return null;
}

// ── Directory helpers ─────────────────────────────────────────────────────────

function ensureDirs(): void {
  for (const d of [BRIDGE_DIR, QUEUE_DIR, RESULTS_DIR]) {
    if (!existsSync(d)) mkdirSync(d, { recursive: true });
  }
}

function generateChunkId(prefix = 'chunk'): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// ── Manifest helpers ───────────────────────────────────────────────────────────

function readManifest(): Manifest | null {
  if (!existsSync(MANIFEST_PATH)) return null;
  try {
    return JSON.parse(readFileSync(MANIFEST_PATH, 'utf-8')) as Manifest;
  } catch {
    return null;
  }
}

function writeManifest(manifest: Manifest): void {
  manifest.updated_at = new Date().toISOString();
  writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2), 'utf-8');
}

function createManifest(
  batchId: string,
  skill: string,
  model: string,
  totalFiles: number,
  options: Record<string, unknown> = {},
): Manifest {
  return {
    batch_id: batchId,
    skill,
    model,
    input_dir: QUEUE_DIR,
    output_dir: RESULTS_DIR,
    total_files: totalFiles,
    processed_files: 0,
    status: 'pending',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    options: { output_format: 'json', schema: 'parameter_set_v1', ...options },
  };
}

// ── Antigravity HTTP send_command ─────────────────────────────────────────────

/**
 * Trigger Antigravity by sending a command via HTTP API.
 * Maps to Python: AntigravityClient("http://localhost:5000").send_command(prompt)
 */
async function sendCommand(prompt: string): Promise<void> {
  // Try common endpoint patterns for the antigravity automation API
  const endpoints = [
    `${ANTIGRAVITY_HTTP}/api/command`,
    `${ANTIGRAVITY_HTTP}/command`,
    `${ANTIGRAVITY_HTTP}/api/v1/command`,
  ];

  let lastErr: unknown;
  for (const url of endpoints) {
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: prompt }),
        signal: AbortSignal.timeout(10_000),
      });
      if (resp.ok) {
        console.error(`[antigravity-client] send_command OK → ${url}`);
        return;
      }
      // 404 → try next endpoint; other errors → throw
      if (resp.status !== 404) {
        const text = await resp.text();
        throw new Error(`send_command HTTP ${resp.status}: ${text.slice(0, 200)}`);
      }
      lastErr = new Error(`HTTP 404 at ${url}`);
    } catch (e) {
      if ((e as Error).message?.includes('fetch')) {
        // Connection refused — Antigravity not running
        throw new Error(`Antigravity HTTP API unreachable at ${ANTIGRAVITY_HTTP}: ${e}`);
      }
      lastErr = e;
    }
  }
  throw new Error(`send_command failed: ${lastErr}`);
}

// ── Antigravity health check ───────────────────────────────────────────────────

async function isAntigravityReachable(): Promise<boolean> {
  const healthEndpoints = [
    `${ANTIGRAVITY_HTTP}/api/health`,
    `${ANTIGRAVITY_HTTP}/health`,
    `${ANTIGRAVITY_HTTP}/`,
  ];
  for (const url of healthEndpoints) {
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(3_000) });
      if (resp.ok || resp.status < 500) return true;
    } catch { /* next */ }
  }
  return false;
}

// ── Result poller ─────────────────────────────────────────────────────────────

/**
 * Poll results/{chunkId}.json every POLL_INTERVAL_MS until it appears or timeout.
 */
async function pollForResult(chunkId: string, timeoutMs: number): Promise<Record<string, unknown>> {
  const resultPath = join(RESULTS_DIR, `${chunkId}.json`);
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    if (existsSync(resultPath)) {
      try {
        const data = JSON.parse(readFileSync(resultPath, 'utf-8'));
        console.error(`[antigravity-client] Result file found: ${resultPath}`);
        return data;
      } catch (e) {
        console.error(`[antigravity-client] Failed to parse result file: ${e}`);
      }
    }
    await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error(`Timeout: no result for chunk_id=${chunkId} after ${timeoutMs}ms`);
}

/**
 * Wait for result via WebSocket (with filesystem polling fallback).
 * Returns parsed JSON from results file or WebSocket message content.
 */
async function waitForResult(chunkId: string, timeoutMs: number): Promise<Record<string, unknown>> {
  // Try WebSocket first (non-blocking — import stream lazily to avoid circular dep)
  let wsResult: Record<string, unknown> | null = null;
  const wsRace = (async () => {
    try {
      const { AntigravityStream } = await import('./antigravity-stream.js');
      const stream = AntigravityStream.getInstance();
      if (!stream.isConnected()) {
        await stream.connect();
      }
      const msg = await stream.waitForResult(chunkId, timeoutMs);
      if (msg.result_path) {
        const p = msg.result_path as string;
        const absPath = existsSync(p) ? p : join(BRIDGE_DIR, p);
        if (existsSync(absPath)) {
          return JSON.parse(readFileSync(absPath, 'utf-8')) as Record<string, unknown>;
        }
      }
      if (msg.content) {
        const parsed = extractJsonFromText(msg.content as string);
        if (parsed) return parsed;
      }
      return msg as Record<string, unknown>;
    } catch (e) {
      console.error(`[antigravity-client] WebSocket wait failed: ${e}. Falling back to polling.`);
      return null;
    }
  })();

  // Race: WebSocket vs filesystem polling
  const pollRace = pollForResult(chunkId, timeoutMs);

  const result = await Promise.race([
    wsRace.then(r => r ?? pollRace),
    pollRace,
  ]);

  wsResult = result;
  return wsResult;
}

// ── Lingya Opus fallback ───────────────────────────────────────────────────────

async function callLingya(
  systemPrompt: string,
  userMessage: string,
): Promise<{ text: string; tokens?: number }> {
  if (!LINGYA_ENDPOINT || !LINGYA_KEY) {
    throw new Error('Lingya API not configured (L0_API_ENDPOINT / L0_API_KEY missing)');
  }

  const url = `${LINGYA_ENDPOINT}/v1/chat/completions`;
  const body = JSON.stringify({
    model: 'claude-opus-4-5',
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userMessage },
    ],
    max_tokens: 2048,
    temperature: 0,
  });

  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${LINGYA_KEY}`,
    },
    body,
  });

  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`Lingya API error: ${resp.status} — ${err.slice(0, 200)}`);
  }

  const data = await resp.json() as {
    choices?: Array<{ message?: { content?: string } }>;
    usage?: { total_tokens?: number };
  };

  const text = data.choices?.[0]?.message?.content ?? '';
  const tokens = data.usage?.total_tokens;
  if (!text) throw new Error('Lingya returned empty response');
  return { text, tokens };
}

// ── Public API ─────────────────────────────────────────────────────────────────

export class AntigravityClient {
  /**
   * Extract formula/parameters from a chunk of text using the file protocol.
   *
   * Flow:
   *   1. Generate chunk_id, write chunk to queue/{chunk_id}.md
   *   2. Update manifest.json
   *   3. send_command() to Antigravity with Skill name + manifest path
   *   4. WebSocket listen OR poll results/{chunk_id}.json
   *   5. Parse result → return ExtractResult
   *   6. Timeout 120s → fallback to Lingya Opus
   */
  async extractChunk(params: {
    chunkText: string;
    skill: SkillName;
    model?: ModelPreference;
    bookId?: string;
  }): Promise<ExtractResult> {
    const skillPrompt = loadSkill(params.skill);
    const modelPref   = params.model ?? 'pro';
    const chunkId     = generateChunkId('chunk');

    // Lingya direct mode (no Antigravity)
    if (modelPref === 'lingya') {
      try {
        const r = await callLingya(skillPrompt, params.chunkText);
        return this._parseExtractResult(r.text, 'lingya_opus', r.tokens);
      } catch (e) {
        return { has_formula: false, reasoning: `Lingya error: ${e}`, model_used: 'lingya_opus' };
      }
    }

    // Try Antigravity via file protocol
    try {
      ensureDirs();

      // 1. Write chunk to queue
      const chunkPath = join(QUEUE_DIR, `${chunkId}.md`);
      writeFileSync(chunkPath, params.chunkText, 'utf-8');

      // 2. Update manifest
      const geminiModel = modelPref === 'flash' ? 'gemini-2.0-flash' : 'gemini-2.5-pro';
      const manifest = createManifest(
        `batch-${Date.now()}`,
        params.skill,
        geminiModel,
        1,
        { book_id: params.bookId ?? 'unknown', chunk_id: chunkId },
      );
      writeManifest(manifest);

      // 3. Trigger Antigravity
      const prompt = [
        `请使用 Skill [${params.skill}] 处理以下任务：`,
        `1. 读取文件: ${chunkPath}`,
        `2. 按照 manifest.json 中的配置处理（路径: ${MANIFEST_PATH}）`,
        `3. 将结果写入: ${join(RESULTS_DIR, `${chunkId}.json`)}`,
        `4. 结果必须是合法 JSON，符合 ${params.skill} 的输出 schema`,
      ].join('\n');

      await sendCommand(prompt);
      console.error(`[antigravity-client] send_command OK for chunk_id=${chunkId}, skill=${params.skill}`);

      // 4. Wait for result (WS + polling)
      const raw = await waitForResult(chunkId, CHUNK_TIMEOUT_MS);
      const modelUsed = `antigravity_${modelPref}`;
      const text = typeof raw.content === 'string' ? raw.content : JSON.stringify(raw);

      return this._parseExtractResult(text, modelUsed, undefined, raw);
    } catch (e) {
      const errMsg = (e as Error).message ?? String(e);
      console.error(`[antigravity-client] Antigravity failed: ${errMsg}. Falling back to Lingya Opus.`);

      // 5. Fallback to Lingya Opus
      try {
        const r = await callLingya(skillPrompt, params.chunkText);
        return this._parseExtractResult(r.text, 'lingya_opus_fallback', r.tokens);
      } catch (e2) {
        return {
          has_formula: false,
          reasoning: `All providers failed. Antigravity: ${errMsg}. Lingya: ${e2}`,
          model_used: 'none',
        };
      }
    }
  }

  /**
   * Batch extract from multiple chunks.
   * All chunks written to queue/, one send_command triggers batch processing.
   *
   * Flow:
   *   1. Write all chunks to queue/
   *   2. Write batch manifest
   *   3. One send_command for entire batch
   *   4. Collect results as they arrive
   *   5. Per-chunk timeout = chunkCount × 60s
   */
  async batchExtract(params: {
    chunks: Array<{ id: string; text: string }>;
    skill: SkillName;
    model?: ModelPreference;
    bookId?: string;
    concurrency?: number;
  }): Promise<Array<{ id: string; result: ExtractResult }>> {
    const modelPref = params.model ?? 'pro';
    const batchId   = `batch-${Date.now()}`;
    const batchTimeoutMs = params.chunks.length * 60_000;

    // Direct Lingya mode
    if (modelPref === 'lingya') {
      const concurrency = Math.min(params.concurrency ?? 3, 5);
      return this._parallelExtract(params.chunks, params.skill, concurrency);
    }

    // Try Antigravity batch mode
    try {
      ensureDirs();

      const chunkMap = new Map<string, string>(); // chunkId → original id

      // 1. Write all chunks to queue/
      for (const chunk of params.chunks) {
        const chunkId = `${batchId}-${chunk.id}`;
        chunkMap.set(chunkId, chunk.id);
        writeFileSync(join(QUEUE_DIR, `${chunkId}.md`), chunk.text, 'utf-8');
      }

      // 2. Write batch manifest
      const geminiModel = modelPref === 'flash' ? 'gemini-2.0-flash' : 'gemini-2.5-pro';
      const manifest = createManifest(
        batchId,
        params.skill,
        geminiModel,
        params.chunks.length,
        { book_id: params.bookId ?? 'unknown', batch_mode: true },
      );
      writeManifest(manifest);

      // 3. One send_command for entire batch
      const prompt = [
        `请使用 Skill [${params.skill}] 批量处理以下任务：`,
        `1. 读取 manifest.json: ${MANIFEST_PATH}`,
        `2. 逐个处理 queue/ 目录中以 "${batchId}" 开头的所有文件`,
        `3. 每个文件的结果写入 results/{文件名}.json（替换 .md → .json）`,
        `4. 所有文件处理完成后，更新 manifest.json 的 status 为 "done"`,
        `5. 输入目录: ${QUEUE_DIR}`,
        `6. 输出目录: ${RESULTS_DIR}`,
      ].join('\n');

      await sendCommand(prompt);
      console.error(`[antigravity-client] Batch send_command OK, batch_id=${batchId}, chunks=${params.chunks.length}`);

      // 4. Collect results
      const results: Array<{ id: string; result: ExtractResult }> = [];
      const chunkIds = Array.from(chunkMap.keys());

      await Promise.all(
        chunkIds.map(async (chunkId) => {
          try {
            const raw = await pollForResult(chunkId, batchTimeoutMs);
            const text = typeof raw.content === 'string' ? raw.content : JSON.stringify(raw);
            const originalId = chunkMap.get(chunkId)!;
            results.push({
              id: originalId,
              result: this._parseExtractResult(text, `antigravity_${modelPref}`, undefined, raw),
            });
          } catch (e) {
            const originalId = chunkMap.get(chunkId)!;
            console.error(`[antigravity-client] Chunk ${chunkId} timeout in batch: ${e}`);
            results.push({
              id: originalId,
              result: { has_formula: false, reasoning: `Timeout: ${e}`, model_used: `antigravity_${modelPref}` },
            });
          }
        }),
      );

      return results;
    } catch (e) {
      const errMsg = (e as Error).message ?? String(e);
      console.error(`[antigravity-client] Batch failed: ${errMsg}. Falling back to parallel Lingya.`);
      return this._parallelExtract(params.chunks, params.skill, params.concurrency ?? 3);
    }
  }

  /**
   * Classify a chunk (science/recipe/narrative/table/reference).
   * Uses Antigravity Flash for speed/cost; falls back to Lingya.
   */
  async classifyChunk(chunkText: string): Promise<ClassifyResult> {
    const systemPrompt = `You are a food science book content classifier.
Classify the following text chunk into exactly one type:
- "science": scientific principles, equations, mechanisms, experimental data
- "recipe": ingredient lists, cooking instructions, proportions, procedures
- "narrative": story, history, general description, no actionable data
- "table": data table without sufficient context
- "reference": bibliography, index, footnotes
- "unknown": cannot determine

Respond with ONLY valid JSON: {"chunk_type": "...", "confidence": 0.0-1.0, "reasoning": "..."}`;

    try {
      const r = await callLingya(systemPrompt, chunkText.slice(0, 2000));
      const parsed = extractJsonFromText(r.text);
      if (!parsed) return { chunk_type: 'unknown', confidence: 0 };
      return {
        chunk_type: (parsed.chunk_type as ClassifyResult['chunk_type']) ?? 'unknown',
        confidence: (parsed.confidence as number) ?? 0.5,
        reasoning: parsed.reasoning as string | undefined,
      };
    } catch {
      return { chunk_type: 'unknown', confidence: 0 };
    }
  }

  /**
   * Multi-label chunk classification.
   * Returns all chunk types with confidence > threshold.
   */
  async classifyChunkMultiLabel(chunkText: string, threshold = 0.5): Promise<MultiLabelClassifyResult> {
    const systemPrompt = `You are a food science book content classifier.
Classify the following text chunk by assigning confidence scores (0.0-1.0) to each type:

Types to evaluate:
- "science": scientific principles, equations, kinetics, heat transfer, experimental data
- "recipe": ingredient lists, cooking instructions, proportions, step-by-step procedures
- "ingredient": ingredient descriptions, varieties, parts, substitutions, composition data
- "sensory": taste/texture/aroma descriptions, flavor profiles, quality evaluation
- "terminology": culinary terminology, technique names, dialect terms, technical jargon
- "narrative": story, history, general description — no actionable quantitative data
- "table": data table (may overlap with science/recipe/ingredient)
- "reference": bibliography, index, footnotes

A single chunk can have multiple types.

Respond ONLY with valid JSON:
{
  "confidence": {
    "science": 0.0, "recipe": 0.0, "ingredient": 0.0, "sensory": 0.0,
    "terminology": 0.0, "narrative": 0.0, "table": 0.0, "reference": 0.0
  },
  "reasoning": "one sentence summary"
}`;

    try {
      const r = await callLingya(systemPrompt, chunkText.slice(0, 2000));
      const parsed = extractJsonFromText(r.text) as Record<string, unknown> | null;
      if (!parsed) return { types: ['narrative'], confidence: { narrative: 0.5 } };

      const conf = (parsed.confidence ?? {}) as Record<string, number>;
      const types = (Object.entries(conf) as [ChunkLabel, number][])
        .filter(([, v]) => v >= threshold)
        .map(([k]) => k);

      return {
        types: types.length > 0 ? types : ['narrative'],
        confidence: conf as Partial<Record<ChunkLabel, number>>,
        reasoning: parsed.reasoning as string | undefined,
      };
    } catch {
      return { types: ['narrative'], confidence: { narrative: 0.5 } };
    }
  }

  /**
   * Health check: can we reach Antigravity HTTP API?
   */
  async healthCheck(): Promise<{ ok: boolean; message: string }> {
    const ok = await isAntigravityReachable();
    return {
      ok,
      message: ok ? `Antigravity HTTP API reachable at ${ANTIGRAVITY_HTTP}` : `Antigravity unreachable at ${ANTIGRAVITY_HTTP}`,
    };
  }

  /**
   * Get bridge directory paths (for diagnostics).
   */
  getBridgePaths(): { bridge: string; queue: string; results: string; manifest: string } {
    return { bridge: BRIDGE_DIR, queue: QUEUE_DIR, results: RESULTS_DIR, manifest: MANIFEST_PATH };
  }

  // ── Private helpers ──────────────────────────────────────────────────────────

  private _parseExtractResult(
    text: string,
    modelUsed: string,
    tokens?: number,
    rawObj?: Record<string, unknown>,
  ): ExtractResult {
    // If rawObj is already structured result, use directly
    if (rawObj && 'has_formula' in rawObj) {
      return {
        ...(rawObj as ExtractResult),
        model_used: modelUsed,
        tokens_used: tokens,
      };
    }

    const parsed = extractJsonFromText(text);
    if (!parsed) {
      return {
        has_formula: false,
        reasoning: 'Failed to parse JSON from response',
        raw_response: text.slice(0, 500),
        model_used: modelUsed,
        tokens_used: tokens,
      };
    }

    return {
      has_formula: Boolean(parsed.has_formula),
      formula_id: parsed.formula_id as string | undefined,
      formula_type: parsed.formula_type as string | undefined,
      formula_name: parsed.formula_name as string | undefined,
      sympy_expression: parsed.sympy_expression as string | undefined,
      reasoning: parsed.reasoning as string | undefined,
      symbols: parsed.symbols as Record<string, unknown> | undefined,
      applicable_range: parsed.applicable_range as Record<string, unknown> | undefined,
      raw_response: text.slice(0, 200),
      model_used: modelUsed,
      tokens_used: tokens,
    };
  }

  private async _parallelExtract(
    chunks: Array<{ id: string; text: string }>,
    skill: SkillName,
    concurrency: number,
  ): Promise<Array<{ id: string; result: ExtractResult }>> {
    const skillPrompt = loadSkill(skill);
    const results: Array<{ id: string; result: ExtractResult }> = [];
    const sem = new Semaphore(Math.min(concurrency, 5));

    await Promise.all(
      chunks.map(async (chunk) => {
        await sem.acquire();
        try {
          const r = await callLingya(skillPrompt, chunk.text);
          results.push({
            id: chunk.id,
            result: this._parseExtractResult(r.text, 'lingya_opus', r.tokens),
          });
        } catch (e) {
          results.push({
            id: chunk.id,
            result: { has_formula: false, reasoning: `Lingya error: ${e}`, model_used: 'lingya_opus' },
          });
        } finally {
          sem.release();
        }
      }),
    );

    return results;
  }
}

// ── Simple semaphore for concurrency control ───────────────────────────────────

class Semaphore {
  private permits: number;
  private queue: Array<() => void> = [];

  constructor(permits: number) {
    this.permits = permits;
  }

  acquire(): Promise<void> {
    if (this.permits > 0) {
      this.permits--;
      return Promise.resolve();
    }
    return new Promise(resolve => this.queue.push(resolve));
  }

  release(): void {
    const next = this.queue.shift();
    if (next) {
      next();
    } else {
      this.permits++;
    }
  }
}

export const antigravityClient = new AntigravityClient();
