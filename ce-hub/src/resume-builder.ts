import { execSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import type { StateStore } from './state-store.js';
import type { TmuxManager } from './tmux-manager.js';

const SESSION = 'cehub';

function exec(cmd: string): string {
  try { return execSync(cmd, { encoding: 'utf-8', timeout: 5000 }).trim(); } catch { return ''; }
}

function getCwd() { return process.env.CE_HUB_CWD || process.cwd(); }

export class ResumeBuilder {
  private store: StateStore;
  private tmux: TmuxManager;
  private checkInterval: ReturnType<typeof setInterval> | null = null;
  private lastSeenAlive = true;

  constructor(store: StateStore, tmux: TmuxManager) {
    this.store = store;
    this.tmux = tmux;
  }

  // Start monitoring CC Lead process
  startMonitoring(): void {
    this.checkInterval = setInterval(() => this.checkCcLead(), 15_000); // every 15s
    console.log('[ResumeBuilder] monitoring cc-lead process');
  }

  private checkCcLead(): void {
    const alive = this.tmux.isAlive('cc-lead');

    if (this.lastSeenAlive && !alive) {
      console.log('[ResumeBuilder] cc-lead exited! Preparing resume...');
      setTimeout(() => this.restartWithResume(), 3000);
    }

    this.lastSeenAlive = alive;
  }

  private restartWithResume(): void {
    // Don't restart if it came back on its own
    if (this.tmux.isAlive('cc-lead')) {
      console.log('[ResumeBuilder] cc-lead already recovered');
      return;
    }

    const resumePrompt = this.buildResumePrompt();
    const cwd = getCwd();

    // Write resume prompt to a temp file
    const resumeFile = join(cwd, '.ce-hub', 'resume-prompt.md');
    writeFileSync(resumeFile, resumePrompt);
    console.log(`[ResumeBuilder] wrote resume prompt to ${resumeFile} (${resumePrompt.length} chars)`);

    // Restart claude in pane 0 with resume context via --resume-from file
    // Strategy: start claude, then tell it to read the resume file as first message
    const cmd = `cd ${cwd} && claude --model opus --dangerously-skip-permissions --agent cc-lead`;
    exec(`tmux send-keys -t ${SESSION}:main.0 '${cmd}' Enter`);

    // After claude starts, point it to the wiki (primary) + resume file (fallback)
    setTimeout(() => {
      const wikiStatus = join(cwd, '.ce-hub', 'wiki', 'STATUS.md');
      const hasWiki = existsSync(wikiStatus);
      const msg = hasWiki
        ? `Read .ce-hub/wiki/STATUS.md for project context, then .ce-hub/resume-prompt.md for recent session state. Report status to Jeff.`
        : `Read .ce-hub/resume-prompt.md — it contains your session recovery context. Then report status to Jeff.`;
      const escaped = msg.replace(/'/g, "'\\''");
      exec(`tmux send-keys -t ${SESSION}:main.0 '${escaped}' Enter`);
      console.log('[ResumeBuilder] cc-lead restarted, sent resume instruction');
    }, 10000);
  }

  buildResumePrompt(): string {
    const sections: string[] = [];

    sections.push('# Session Resume — CC Lead Recovery');
    sections.push('你的上一个 session 结束了，这是自动恢复。以下是你需要知道的上下文：');
    sections.push('');

    // Recent tasks
    const tasks = this.store.listTasks();
    const inProgress = tasks.filter(t => t.status === 'in_progress' || t.status === 'running');
    const pending = tasks.filter(t => t.status === 'pending' || t.status === 'queued');
    const recentDone = tasks.filter(t => t.status === 'done').sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0)).slice(0, 5);

    if (inProgress.length > 0) {
      sections.push('## 进行中的任务（需要跟进）');
      for (const t of inProgress) {
        sections.push(`- **${t.title}** → ${t.to_agent} (since ${new Date(t.started_at || t.created_at).toLocaleString()})`);
      }
      sections.push('');
    }

    if (pending.length > 0) {
      sections.push('## 等待中的任务');
      for (const t of pending.slice(0, 10)) {
        sections.push(`- ${t.title} → ${t.to_agent} (P${t.priority})`);
      }
      sections.push('');
    }

    if (recentDone.length > 0) {
      sections.push('## 最近完成的任务');
      for (const t of recentDone) {
        const summary = t.result?.summary || '';
        sections.push(`- ${t.title} (${t.to_agent}): ${summary}`);
      }
      sections.push('');
    }

    // Recent events
    const events = this.store.listRecentEvents();
    if (events.length > 0) {
      sections.push('## 最近事件');
      for (const e of events.slice(0, 8)) {
        const time = new Date(e.created_at).toLocaleTimeString();
        sections.push(`- [${time}] ${e.type}: ${e.source}${e.target ? ' → ' + e.target : ''}`);
      }
      sections.push('');
    }

    // Agent memory
    const memoryDir = join(getCwd(), '.ce-hub', 'memory', 'cc-lead');
    if (existsSync(memoryDir)) {
      try {
        const files = readdirSync(memoryDir).filter(f => f.endsWith('.md'));
        for (const f of files) {
          const content = readFileSync(join(memoryDir, f), 'utf-8').trim();
          if (content) {
            sections.push(`## Memory: ${f}`);
            sections.push(content.slice(0, 500));
            sections.push('');
          }
        }
      } catch {}
    }

    // Active agents
    const agentWindows = this.tmux.listWindows();
    const alive = agentWindows.filter(a => a.alive);
    if (alive.length > 0) {
      sections.push('## 当前在线 Agent');
      for (const a of alive) {
        sections.push(`- ${a.name}`);
      }
      sections.push('');
    }

    sections.push('---');
    sections.push('请先检查进行中的任务状态，然后等待 Jeff 的指令。');

    return sections.join('\n');
  }

  stop(): void {
    if (this.checkInterval) clearInterval(this.checkInterval);
  }
}
