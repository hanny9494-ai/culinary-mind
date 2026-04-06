import type { StateStore } from './state-store.js';

interface CostEntry {
  agent: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  task_id?: string;
}

interface Budget {
  period: 'daily' | 'weekly' | 'monthly';
  limit_usd: number;
  action: 'warn' | 'downgrade' | 'pause';
}

// Approximate pricing per 1M tokens (USD)
const PRICING: Record<string, { input: number; output: number }> = {
  'opus': { input: 15, output: 75 },
  'sonnet': { input: 3, output: 15 },
  'haiku': { input: 0.25, output: 1.25 },
  'codex': { input: 3, output: 15 },        // approximate
  'gemini-2.5-pro': { input: 1.25, output: 5 },
  'flash': { input: 0.075, output: 0.3 },   // DashScope flash
};

export class CostTracker {
  private store: StateStore;
  private budgets: Budget[] = [
    { period: 'daily', limit_usd: 50, action: 'warn' },
  ];
  private sessionCosts = new Map<string, number>();

  constructor(store: StateStore) { this.store = store; }

  initialize(): void {
    // Ensure cost_log table
    try {
      (this.store as any).db.exec(`
        CREATE TABLE IF NOT EXISTS cost_log (
          id TEXT PRIMARY KEY, agent_name TEXT, model TEXT,
          input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
          task_id TEXT, created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS budget_config (
          id TEXT PRIMARY KEY, period TEXT, limit_usd REAL, action TEXT
        );
      `);
    } catch {}
    console.log(`[CostTracker] initialized`);
  }

  // Log a cost entry
  log(entry: CostEntry): void {
    const cost = entry.cost_usd || this.estimateCost(entry.model, entry.input_tokens, entry.output_tokens);
    try {
      (this.store as any).db.prepare(
        `INSERT INTO cost_log (id, agent_name, model, input_tokens, output_tokens, cost_usd, task_id, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      ).run(
        `cost_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        entry.agent, entry.model, entry.input_tokens, entry.output_tokens,
        cost, entry.task_id || null, Date.now()
      );
    } catch {}

    // Track session total
    const prev = this.sessionCosts.get(entry.agent) || 0;
    this.sessionCosts.set(entry.agent, prev + cost);

    // Check budget
    this.checkBudget();
  }

  estimateCost(model: string, inputTokens: number, outputTokens: number): number {
    const p = PRICING[model] || PRICING['sonnet'];
    return (inputTokens * p.input + outputTokens * p.output) / 1_000_000;
  }

  // Get costs for current period
  getPeriodCost(period: 'daily' | 'weekly' | 'monthly'): number {
    const now = Date.now();
    const cutoff = period === 'daily' ? now - 86400_000
      : period === 'weekly' ? now - 604800_000
      : now - 2592000_000;
    try {
      const row = (this.store as any).db.prepare(
        `SELECT SUM(cost_usd) as total FROM cost_log WHERE created_at > ?`
      ).get(cutoff) as { total: number | null };
      return row?.total || 0;
    } catch { return 0; }
  }

  getSessionCosts(): Record<string, number> {
    return Object.fromEntries(this.sessionCosts);
  }

  getTotalSessionCost(): number {
    let total = 0;
    for (const v of this.sessionCosts.values()) total += v;
    return total;
  }

  // Get per-agent breakdown
  getAgentCosts(): Record<string, { tokens: number; cost_usd: number; calls: number }> {
    try {
      const rows = (this.store as any).db.prepare(
        `SELECT agent_name, SUM(input_tokens + output_tokens) as tokens, SUM(cost_usd) as cost, COUNT(*) as calls
         FROM cost_log GROUP BY agent_name`
      ).all() as any[];
      const result: Record<string, { tokens: number; cost_usd: number; calls: number }> = {};
      for (const r of rows) result[r.agent_name] = { tokens: r.tokens, cost_usd: r.cost, calls: r.calls };
      return result;
    } catch { return {}; }
  }

  private checkBudget(): void {
    for (const budget of this.budgets) {
      const spent = this.getPeriodCost(budget.period);
      const pct = spent / budget.limit_usd;
      if (pct >= 1.0) {
        console.warn(`[CostTracker] ⚠️ ${budget.period} budget EXCEEDED: $${spent.toFixed(2)} / $${budget.limit_usd}`);
      } else if (pct >= 0.8) {
        console.warn(`[CostTracker] ⚠️ ${budget.period} budget at ${(pct * 100).toFixed(0)}%: $${spent.toFixed(2)} / $${budget.limit_usd}`);
      }
    }
  }
}
