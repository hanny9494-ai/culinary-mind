/**
 * ModelRouter — Automatic model selection by task type
 *
 * Routes different extraction tasks to different model backends.
 * Priority: Coding Plan models (free quota) → Flash → Lingya Opus
 *
 * Model map:
 *   classify:  qwen3.5-plus → qwen3.5-flash (DashScope fallback)
 *   skill_a:   gemini-pro (Antigravity) → lingya-opus
 *   skill_b:   kimi-k2.5 → qwen3.5-flash
 *   skill_c:   gemini-flash → qwen3.5-flash
 *   skill_d:   glm-5 → qwen3.5-flash
 *   qc:        qwen3.5-plus → qwen3.5-flash
 */

export type SkillKey = 'A' | 'B' | 'C' | 'D';
export type TaskType = 'classify' | `skill_${Lowercase<SkillKey>}` | 'qc' | 'batch';

export interface ModelChoice {
  provider: 'antigravity' | 'dashscope' | 'kimi' | 'glm' | 'lingya';
  model: string;
  api_model: string;  // model name to pass in API call
  tier: 'pro' | 'flash';
  fallback?: ModelChoice;
}

// ── Model definitions ──────────────────────────────────────────────────────────

const ANTIGRAVITY_PRO: ModelChoice = {
  provider: 'antigravity', model: 'gemini-pro', api_model: 'gemini-2.5-pro',
  tier: 'pro',
  fallback: {
    provider: 'lingya', model: 'lingya-opus', api_model: 'claude-opus-4-5',
    tier: 'pro',
  },
};

const ANTIGRAVITY_FLASH: ModelChoice = {
  provider: 'antigravity', model: 'gemini-flash', api_model: 'gemini-2.0-flash',
  tier: 'flash',
  fallback: {
    provider: 'dashscope', model: 'qwen3.5-flash', api_model: 'qwen-plus',
    tier: 'flash',
  },
};

const DASHSCOPE_PLUS: ModelChoice = {
  provider: 'dashscope', model: 'qwen3.5-plus', api_model: 'qwen-plus',
  tier: 'pro',
  fallback: {
    provider: 'dashscope', model: 'qwen3.5-flash', api_model: 'qwen-turbo',
    tier: 'flash',
  },
};

const KIMI_K2: ModelChoice = {
  provider: 'kimi', model: 'kimi-k2.5', api_model: 'moonshot-v1-8k',
  tier: 'flash',
  fallback: {
    provider: 'dashscope', model: 'qwen3.5-flash', api_model: 'qwen-turbo',
    tier: 'flash',
  },
};

const GLM_5: ModelChoice = {
  provider: 'glm', model: 'glm-5', api_model: 'glm-4-flash',
  tier: 'flash',
  fallback: {
    provider: 'dashscope', model: 'qwen3.5-flash', api_model: 'qwen-turbo',
    tier: 'flash',
  },
};

// ── Routing table ──────────────────────────────────────────────────────────────

const ROUTING_TABLE: Record<TaskType, ModelChoice> = {
  classify:  DASHSCOPE_PLUS,
  skill_a:   ANTIGRAVITY_PRO,
  skill_b:   KIMI_K2,
  skill_c:   ANTIGRAVITY_FLASH,
  skill_d:   GLM_5,
  qc:        DASHSCOPE_PLUS,
  batch:     ANTIGRAVITY_FLASH,
};

// ── Public API ─────────────────────────────────────────────────────────────────

export function getModelForTask(task: TaskType): ModelChoice {
  return ROUTING_TABLE[task] ?? ANTIGRAVITY_FLASH;
}

export function getModelForSkill(skill: SkillKey): ModelChoice {
  const key: TaskType = `skill_${skill.toLowerCase() as Lowercase<SkillKey>}`;
  return getModelForTask(key);
}

/**
 * Convert a ModelChoice to the AntigravityClient model preference.
 * This is used when the provider is 'antigravity' or 'lingya' (which go via AntigravityClient).
 */
export function toAntigravityModelPref(choice: ModelChoice): 'pro' | 'flash' | 'lingya' {
  if (choice.provider === 'lingya') return 'lingya';
  if (choice.tier === 'pro') return 'pro';
  return 'flash';
}

/**
 * Get a summary of all routing decisions (for logging/debugging).
 */
export function getRoutingTable(): Array<{ task: string; primary: string; fallback: string }> {
  return Object.entries(ROUTING_TABLE).map(([task, choice]) => ({
    task,
    primary: `${choice.provider}/${choice.model}`,
    fallback: choice.fallback ? `${choice.fallback.provider}/${choice.fallback.model}` : 'none',
  }));
}
