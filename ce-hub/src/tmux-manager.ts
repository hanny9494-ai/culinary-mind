import { execSync } from 'node:child_process';
import { readFileSync, existsSync, readdirSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { AgentDefinition } from './types.js';

const SESSION = 'cehub';

// Lazy getters to avoid ESM import hoisting issues
function getCwd() { return process.env.CE_HUB_CWD || process.cwd(); }
function getAgentsDir() { return process.env.CE_HUB_AGENTS_DIR || join(getCwd(), '.claude', 'agents'); }
function getMemoryDir() { return join(getCwd(), '.ce-hub', 'memory'); }

function exec(cmd: string): string {
  try { return execSync(cmd, { encoding: 'utf-8', timeout: 5000, cwd: getCwd() }).trim(); } catch { return ''; }
}

function parseFrontmatter(content: string): { meta: Record<string, string>; body: string } {
  const m = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) return { meta: {}, body: content };
  const meta: Record<string, string> = {};
  for (const line of m[1].split('\n')) {
    const i = line.indexOf(':');
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return { meta, body: m[2].trim() };
}

// File protocol instructions injected into every agent
const PROTOCOL_PROMPT = `
## ce-hub Communication Protocol — MANDATORY

You are managed by ce-hub. All task communication goes through files. Follow these rules strictly.

### When you receive a message starting with "You have a new task in .ce-hub/inbox/"
1. Read the JSON file(s) in your inbox directory immediately
2. Execute the task described in the JSON
3. When done, you MUST write a result file (see below)

### Receiving tasks
Your inbox: .ce-hub/inbox/{your-name}/
Read all .json files there. Each contains: {"from", "type", "content", "task_id"}

### MANDATORY: Reporting results
After completing ANY task from your inbox, you MUST write a result JSON file:

\`\`\`bash
cat > .ce-hub/results/result_{your-name}_{timestamp}.json << 'RESULT_EOF'
{
  "from": "{your-name}",
  "task_id": "{task_id from inbox file}",
  "status": "done",
  "summary": "Brief description of what you accomplished",
  "output_files": ["list of files you created or modified"]
}
RESULT_EOF
\`\`\`

Use status "done" for success, "failed" for failure (include error in summary), "partial" if incomplete.

THIS IS NOT OPTIONAL. The orchestrator (CC Lead) depends on result files to track progress.
If you don't write a result file, the task stays stuck as "in_progress" forever.

### Self-polling
After completing each task, check your inbox (.ce-hub/inbox/{your-name}/) for new tasks.
If you see a short notification "New task in inbox", read all .json files in your inbox immediately.

### Dispatching to other agents
Write JSON to .ce-hub/dispatch/:
{"from":"{your-name}","to":"target-agent","task":"description","priority":1}

### Project knowledge (wiki)
All compiled project knowledge is in /Users/jeff/culinary-mind/wiki/:
- Project status: /Users/jeff/culinary-mind/wiki/STATUS.md (read this first when starting work)
- Your agent context: /Users/jeff/culinary-mind/wiki/agents/{your-name}.md
- Architecture: /Users/jeff/culinary-mind/wiki/ARCHITECTURE.md
- Decisions: /Users/jeff/culinary-mind/wiki/DECISIONS.md

The wiki is auto-compiled from raw/ by wiki-curator. Read wiki/ freely. Do NOT write to it.
After completing work, write result files — wiki-curator will update the wiki.

### Wiki Write Invariant — ABSOLUTE RULE
You must NEVER write to /Users/jeff/culinary-mind/wiki/ directly.
Only the wiki-curator agent has write rights to wiki/.
If you produce knowledge that belongs in wiki/, write it as a result file to .ce-hub/results/ — wiki-curator will pick it up on its next run.
Violation of this rule is a P0 architectural error.

### Output Placement Rules
Your outputs fall into two categories:
- **Result summary** → write .ce-hub/results/result_{your-name}_{timestamp}.json (mandatory, every task)
- **Long documents** (research reports / architecture proposals / design docs / PR docs) → write raw/{your-type}/{topic}.md

Your type maps to your agent name:
- researcher → raw/research/
- architect → raw/architecture/
- coder → raw/coder/
- others → raw/{name}/ (create as needed)

Never write to wiki/. wiki-curator distills from raw/.
`.trim();

export class TmuxManager {
  private defs = new Map<string, AgentDefinition>();

  initialize(): void {
    // Ensure tmux session exists
    if (!exec(`tmux has-session -t ${SESSION} 2>&1 && echo ok`).includes('ok')) {
      exec(`tmux new-session -d -s ${SESSION} -n dashboard -x 200 -y 50`);
      console.log(`[TmuxManager] created tmux session: ${SESSION}`);
    }

    // Load agent definitions
    if (existsSync(getAgentsDir())) {
      for (const f of readdirSync(getAgentsDir()).filter((f: string) => f.endsWith('.md') && !f.startsWith('_'))) {
        const { meta, body } = parseFrontmatter(readFileSync(join(getAgentsDir(), f), 'utf8'));
        const name = meta['name'] || f.replace('.md', '');
        this.defs.set(name, {
          name, description: meta['description'] || '',
          tools: meta['tools'] ? meta['tools'].split(',').map((t: string) => t.trim()) : [],
          model: meta['model'] || 'sonnet',
          systemPrompt: body,
        });
      }
    }
    // cc-lead always available
    if (!this.defs.has('cc-lead')) {
      this.defs.set('cc-lead', {
        name: 'cc-lead', description: 'CC Lead — 指挥中心',
        tools: [], model: 'opus',
        systemPrompt: 'You are CC Lead, the orchestration hub for culinary-engine.',
      });
    }
    console.log(`[TmuxManager] loaded ${this.defs.size} agent definitions`);
  }

  getDefinition(name: string): AgentDefinition | undefined { return this.defs.get(name); }
  getDefinitions(): AgentDefinition[] { return [...this.defs.values()]; }

  resolveCommand(def: AgentDefinition): string {
    const model = def.model.toLowerCase();
    // Load agent memory if exists
    const memoryDir = join(getMemoryDir(), def.name);
    let memoryAppend = '';
    if (existsSync(memoryDir)) {
      try {
        const files = readdirSync(memoryDir).filter((f: string) => f.endsWith('.md'));
        const contents = files.map((f: string) => readFileSync(join(memoryDir, f), 'utf8')).join('\n\n');
        if (contents.trim()) memoryAppend = contents;
      } catch {}
    }

    const appendPrompt = [PROTOCOL_PROMPT, memoryAppend].filter(Boolean).join('\n\n');

    if (model === 'codex') {
      return `codex exec --dangerously-bypass-approvals-and-sandbox`;
    }
    if (model.startsWith('gemini')) {
      return `python3 scripts/gemini_agent.py --model ${model}`;
    }

    // Write prompt to temp file to avoid shell escaping issues with quotes/parens
    const promptDir = join(getCwd(), '.ce-hub', 'tmp');
    if (!existsSync(promptDir)) mkdirSync(promptDir, { recursive: true });
    const promptFile = join(promptDir, `${def.name}-append.md`);
    writeFileSync(promptFile, appendPrompt);

    // Default: claude with agent definition for proper tools/permissions
    const claudeModel = model === 'opus' ? 'opus' : model === 'haiku' ? 'haiku' : 'sonnet';
    // Use --agent flag if agent .md file exists (gives agent its tools like web_search)
    const agentFile = join(getAgentsDir(), `${def.name}.md`);
    const agentFlag = existsSync(agentFile) ? `--agent ${def.name}` : '';
    return `claude --model ${claudeModel} --dangerously-skip-permissions ${agentFlag} --append-system-prompt-file ${promptFile}`;
  }

  private validateName(name: string): void {
    if (!/^[a-z0-9_-]+$/i.test(name)) throw new Error(`Invalid agent name: ${name}`);
  }

  startAgent(agentName: string): boolean {
    this.validateName(agentName);
    if (this.isAlive(agentName)) {
      console.log(`[TmuxManager] ${agentName} already running`);
      return true;
    }

    const def = this.defs.get(agentName);
    if (!def) { console.error(`[TmuxManager] unknown agent: ${agentName}`); return false; }

    const cmd = this.resolveCommand(def);
    console.log(`[TmuxManager] starting ${agentName}: ${cmd.slice(0, 80)}...`);

    // Prefer reusing existing pane (agent exited, pane still has its title) over opening new window
    const existingPane = this.findAgentPane(agentName);
    if (existingPane) {
      // Send command to the existing bash pane
      exec(`tmux send-keys -t '${existingPane}' 'cd ${getCwd()} && ${cmd}' Enter`);
      console.log(`[TmuxManager] restarted ${agentName} in existing pane ${existingPane}`);
    } else {
      exec(`tmux new-window -d -t ${SESSION} -n ${agentName} 'cd ${getCwd()} && ${cmd}'`);
      console.log(`[TmuxManager] started ${agentName} in new window`);
    }
    return true;
  }

  // Find an existing pane with this agent's title (may be bare bash after agent exited)
  private findAgentPane(agentName: string): string | null {
    const panes = exec(`tmux list-panes -t ${SESSION}:main -F '#{pane_title}\t#{pane_id}' 2>/dev/null`).split('\n');
    for (const p of panes) {
      const sep = p.lastIndexOf('\t');
      if (sep < 0) continue;
      const title = p.slice(0, sep);
      const id = p.slice(sep + 1);
      if (title === agentName || title.includes(agentName)) return id;
    }
    return null;
  }

  // Send a message to agent: full content to inbox file + short tmux notification
  sendMessage(agentName: string, message: string): void {
    this.validateName(agentName);

    // Start agent if not running
    if (!this.isAlive(agentName)) {
      console.log(`[TmuxManager] ${agentName} not running, starting...`);
      this.startAgent(agentName);
    }

    // Step 1: Write full content to inbox file
    const inboxDir = join(getCwd(), '.ce-hub', 'inbox', agentName);
    if (!existsSync(inboxDir)) { exec(`mkdir -p '${inboxDir}'`); }
    const timestamp = Date.now();
    const taskFile = join(inboxDir, `msg_${timestamp}.json`);
    writeFileSync(taskFile, JSON.stringify({
      from: 'cc-lead', type: 'message', content: message,
      task_id: `msg_${timestamp}`, created_at: new Date().toISOString(),
    }, null, 2));

    // Step 2: Short one-line tmux notification (< 80 chars, won't corrupt TUI)
    const target = this.findAgentTarget(agentName);
    if (target) {
      // Use plain ASCII to avoid multibyte char issues, clear input first, delay before Enter
      const note = `New task in .ce-hub/inbox/${agentName}/ - read and execute`;
      // Clear any stale input in the TUI input box
      exec(`tmux send-keys -t '${target}' C-u`);
      // Type notification literally
      exec(`tmux send-keys -t '${target}' -l '${note.replace(/'/g, "'\\''")}'`);
      // Brief delay to let TUI ingest the typed characters before Enter
      exec(`sleep 0.3`);
      exec(`tmux send-keys -t '${target}' Enter`);
    }

    console.log(`[TmuxManager] notified ${agentName}: inbox msg_${timestamp}.json`);
  }

  // Find the tmux target for an agent — checks pane titles in main window first, then windows
  // Claude Code may prefix pane titles with "✳ " or similar, so we use fuzzy matching
  private findAgentTarget(agentName: string): string | null {
    // Check panes in main window (by pane title containing agent name)
    const panes = exec(`tmux list-panes -t ${SESSION}:main -F '#{pane_title}\t#{pane_id}' 2>/dev/null`).split('\n').filter(Boolean);
    for (const p of panes) {
      const sep = p.lastIndexOf('\t');
      if (sep < 0) continue;
      const title = p.slice(0, sep);
      const id = p.slice(sep + 1);
      if (title === agentName || title.includes(agentName)) return id;
    }
    // Check windows by name
    const windows = exec(`tmux list-windows -t ${SESSION} -F '#{window_name}' 2>/dev/null`).split('\n');
    if (windows.includes(agentName)) return `${SESSION}:${agentName}`;
    return null;
  }

  isAlive(agentName: string): boolean {
    // Check panes in main window by title + verify pane has child processes (claude runs as child of bash)
    const panes = exec(`tmux list-panes -t ${SESSION}:main -F '#{pane_title}\t#{pane_pid}' 2>/dev/null`).split('\n');
    for (const p of panes) {
      const sep = p.lastIndexOf('\t');
      if (sep < 0) continue;
      const title = p.slice(0, sep);
      const pid = p.slice(sep + 1);
      if (title === agentName || title?.includes(agentName)) {
        // Check if pane's shell has any child processes (bare bash = no children)
        const children = exec(`pgrep -P ${pid} 2>/dev/null`);
        if (children.trim()) return true;
      }
    }
    // Check windows by name (separate windows always have agent running)
    return exec(`tmux list-windows -t ${SESSION} -F '#{window_name}' 2>/dev/null`).split('\n').includes(agentName);
  }

  listWindows(): { name: string; alive: boolean }[] {
    const windows = exec(`tmux list-windows -t ${SESSION} -F '#{window_name}' 2>/dev/null`).split('\n').filter(Boolean);
    // Check pane title + child processes (claude runs as child of bash)
    const paneInfo = exec(`tmux list-panes -t ${SESSION}:main -F '#{pane_title}\t#{pane_pid}' 2>/dev/null`).split('\n').filter(Boolean);
    return this.getDefinitions().map(d => ({
      name: d.name,
      alive: windows.includes(d.name) || paneInfo.some(p => {
        const sep = p.lastIndexOf('\t');
        if (sep < 0) return false;
        const title = p.slice(0, sep);
        const pid = p.slice(sep + 1);
        if (title === d.name || title?.includes(d.name)) {
          return exec(`pgrep -P ${pid} 2>/dev/null`).trim().length > 0;
        }
        return false;
      }),
    }));
  }

  killAgent(agentName: string): void {
    exec(`tmux send-keys -t ${SESSION}:${agentName} C-c`);
    exec(`tmux kill-window -t ${SESSION}:${agentName} 2>/dev/null`);
    console.log(`[TmuxManager] killed ${agentName}`);
  }

  shutdown(): void {
    exec(`tmux kill-session -t ${SESSION} 2>/dev/null`);
  }
}
