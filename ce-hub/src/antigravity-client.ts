/**
 * Antigravity Gateway Client
 *
 * Calls Antigravity Gateway API (http://127.0.0.1:18789/api/v1/chat)
 * with automatic fallback chain:
 *   1. Antigravity Pro (Gemini Pro via Gateway)
 *   2. Antigravity Flash (Gemini Flash via Gateway)
 *   3. Lingya Opus (direct L0_API_ENDPOINT — no proxy)
 *
 * IMPORTANT: trust_env=false bypasses local proxy 127.0.0.1:7890
 * Achieved via explicit no-proxy agent (not relying on environment).
 */

import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const ANTIGRAVITY_BASE = process.env.ANTIGRAVITY_API || 'http://127.0.0.1:18789';
const LINGYA_ENDPOINT = process.env.L0_API_ENDPOINT || '';
const LINGYA_KEY = process.env.L0_API_KEY || '';
const SKILLS_DIR = process.env.CE_HUB_CWD
  ? join(process.env.CE_HUB_CWD, '.gemini', 'skills')
  : join(process.cwd(), '..', '.gemini', 'skills');

export type SkillName =
  | 'parameter-extractor-a'
  | 'parameter-extractor-b'
  | 'culinary-architect'
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
}

export interface ClassifyResult {
  chunk_type: 'science' | 'recipe' | 'narrative' | 'table' | 'reference' | 'unknown';
  confidence: number;
  reasoning?: string;
}

// ── Skill loading ─────────────────────────────────────────────────────────────

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
  console.warn(`[antigravity-client] Skill not found: ${skillName} (searched ${paths.join(', ')})`);
  return `You are a food science parameter extraction assistant. Extract structured data from the provided text.`;
}

// ── JSON extraction from LLM response ─────────────────────────────────────────

function extractJsonFromText(text: string): Record<string, unknown> | null {
  // Try raw parse first
  try { return JSON.parse(text.trim()); } catch { /* fall through */ }

  // Strip markdown fences
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced) {
    try { return JSON.parse(fenced[1].trim()); } catch { /* fall through */ }
  }

  // Extract first {...} block
  const braceMatch = text.match(/\{[\s\S]*\}/);
  if (braceMatch) {
    try { return JSON.parse(braceMatch[0]); } catch { /* fall through */ }
  }

  return null;
}

// ── Antigravity Gateway call ──────────────────────────────────────────────────

async function callAntigravity(
  message: string,
  model: 'pro' | 'flash',
  agentId = 'pipeline-extract',
): Promise<{ text: string; tokens?: number }> {
  const url = `${ANTIGRAVITY_BASE}/api/v1/chat`;
  const body = JSON.stringify({
    agent: agentId,
    message,
    model: model === 'pro' ? 'gemini-2.5-pro' : 'gemini-2.0-flash',
    stream: false,
  });

  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    // Note: Node.js fetch doesn't use env proxies by default (trust_env=false equiv)
  });

  if (!resp.ok) {
    throw new Error(`Antigravity API error: ${resp.status} ${resp.statusText}`);
  }

  const data = await resp.json() as { reply?: string; message?: string; content?: string; usage?: { total_tokens?: number } };
  const text = data.reply ?? data.message ?? data.content ?? '';
  const tokens = data.usage?.total_tokens;

  if (!text) throw new Error('Antigravity returned empty response');
  return { text, tokens };
}

// ── Lingya Opus fallback ──────────────────────────────────────────────────────

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
    throw new Error(`Lingya API error: ${resp.status} — ${err}`);
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

// ── Public API ────────────────────────────────────────────────────────────────

export class AntigravityClient {
  /**
   * Extract formula/parameters from a chunk of text using Skill A or B.
   * Fallback chain: Pro → Flash → Lingya Opus
   */
  async extractChunk(params: {
    chunkText: string;
    skill: SkillName;
    model?: ModelPreference;
    bookId?: string;
  }): Promise<ExtractResult> {
    const skillPrompt = loadSkill(params.skill);
    const fullMessage = `${skillPrompt}\n\n---\n\nExtract from the following text:\n\n${params.chunkText}`;
    const modelPref = params.model ?? 'pro';

    let rawText = '';
    let modelUsed = '';
    let tokensUsed: number | undefined;

    const tryFetch = async () => {
      if (modelPref === 'lingya') {
        // Direct Lingya Opus
        const r = await callLingya(skillPrompt, params.chunkText);
        rawText = r.text; modelUsed = 'lingya_opus'; tokensUsed = r.tokens;
        return;
      }

      // Try Antigravity Pro first (or Flash if requested)
      const primary = modelPref === 'flash' ? 'flash' : 'pro';
      try {
        const r = await callAntigravity(fullMessage, primary);
        rawText = r.text; modelUsed = `antigravity_${primary}`; tokensUsed = r.tokens;
        return;
      } catch (err) {
        console.warn(`[antigravity-client] ${primary} failed: ${err}. Trying fallback...`);
      }

      // Fallback to Flash (if Pro was primary)
      if (primary === 'pro') {
        try {
          const r = await callAntigravity(fullMessage, 'flash');
          rawText = r.text; modelUsed = 'antigravity_flash'; tokensUsed = r.tokens;
          return;
        } catch (err) {
          console.warn(`[antigravity-client] Flash fallback failed: ${err}. Trying Lingya...`);
        }
      }

      // Final fallback: Lingya Opus
      const r = await callLingya(skillPrompt, params.chunkText);
      rawText = r.text; modelUsed = 'lingya_opus'; tokensUsed = r.tokens;
    };

    await tryFetch();

    const parsed = extractJsonFromText(rawText);
    if (!parsed) {
      return {
        has_formula: false,
        reasoning: 'Failed to parse JSON from response',
        raw_response: rawText.slice(0, 500),
        model_used: modelUsed,
        tokens_used: tokensUsed,
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
      raw_response: rawText.slice(0, 200),
      model_used: modelUsed,
      tokens_used: tokensUsed,
    };
  }

  /**
   * Classify a chunk (science/recipe/narrative/table/reference).
   * Uses Flash for speed/cost efficiency.
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

    const fullMessage = `${systemPrompt}\n\n---\n\nClassify:\n${chunkText.slice(0, 2000)}`;

    let rawText = '';
    try {
      const r = await callAntigravity(fullMessage, 'flash');
      rawText = r.text;
    } catch {
      // Classification is best-effort; return unknown on total failure
      return { chunk_type: 'unknown', confidence: 0 };
    }

    const parsed = extractJsonFromText(rawText);
    if (!parsed) return { chunk_type: 'unknown', confidence: 0 };

    return {
      chunk_type: (parsed.chunk_type as ClassifyResult['chunk_type']) ?? 'unknown',
      confidence: (parsed.confidence as number) ?? 0.5,
      reasoning: parsed.reasoning as string | undefined,
    };
  }

  /**
   * Health check: can we reach Antigravity Gateway?
   */
  async healthCheck(): Promise<{ ok: boolean; message: string }> {
    try {
      const resp = await fetch(`${ANTIGRAVITY_BASE}/api/v1/health`, {
        signal: AbortSignal.timeout(5000),
      });
      return { ok: resp.ok, message: resp.ok ? 'Antigravity Gateway reachable' : `HTTP ${resp.status}` };
    } catch (err) {
      return { ok: false, message: `Antigravity unreachable: ${err}` };
    }
  }
}

export const antigravityClient = new AntigravityClient();
