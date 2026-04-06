import { execSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import type { StateStore } from './state-store.js';

function getCwd() { return process.env.CE_HUB_CWD || process.cwd(); }
function getGatesFile() { return join(getCwd(), '.ce-hub', 'quality-gates.json'); }

interface GateRule {
  check: string;                    // command or @agent dispatch
  pass_criteria: Record<string, number>;
  on_fail: 'retry' | 'flag_for_review' | 'send_back_to_coder';
  max_retries?: number;
}

export class QualityGate {
  private gates: Record<string, GateRule> = {};

  initialize(): void {
    if (existsSync(getGatesFile())) {
      try { this.gates = JSON.parse(readFileSync(getGatesFile(), 'utf-8')); } catch {}
    }
    console.log(`[QualityGate] loaded ${Object.keys(this.gates).length} gate rules`);
  }

  // Run QC for a specific task type
  async check(taskType: string, outputFile?: string): Promise<{ passed: boolean; details: Record<string, unknown> }> {
    const rule = this.gates[taskType];
    if (!rule) return { passed: true, details: { reason: 'no gate rule defined' } };

    let cmd = rule.check;
    if (outputFile) cmd = cmd.replace('{output_file}', outputFile);

    // Skip @agent dispatches (handled separately)
    if (cmd.startsWith('@')) {
      return { passed: true, details: { reason: 'agent review required', agent: cmd } };
    }

    try {
      const output = execSync(cmd, { cwd: getCwd(), encoding: 'utf-8', timeout: 60_000 });
      // Try to parse output as JSON for criteria checking
      try {
        const metrics = JSON.parse(output);
        let passed = true;
        const failures: string[] = [];
        for (const [key, threshold] of Object.entries(rule.pass_criteria)) {
          if (key.endsWith('_min') && metrics[key.replace('_min', '')] < threshold) {
            passed = false;
            failures.push(`${key}: ${metrics[key.replace('_min', '')]} < ${threshold}`);
          }
          if (key.endsWith('_max') && metrics[key.replace('_max', '')] > threshold) {
            passed = false;
            failures.push(`${key}: ${metrics[key.replace('_max', '')]} > ${threshold}`);
          }
        }
        return { passed, details: { metrics, failures } };
      } catch {
        // Non-JSON output, assume pass if exit code 0
        return { passed: true, details: { output: output.slice(0, 500) } };
      }
    } catch (err) {
      return { passed: false, details: { error: String(err) } };
    }
  }

  getOnFail(taskType: string): string {
    return this.gates[taskType]?.on_fail || 'flag_for_review';
  }

  getMaxRetries(taskType: string): number {
    return this.gates[taskType]?.max_retries || 2;
  }
}
