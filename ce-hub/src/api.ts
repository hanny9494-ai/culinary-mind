import Fastify from 'fastify';
import cors from '@fastify/cors';
import { readFileSync, statSync, existsSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { StateStore } from './state-store.js';
import type { TaskEngine } from './task-engine.js';
import type { TmuxManager } from './tmux-manager.js';
import type { CostTracker } from './cost-tracker.js';
import type { MemoryManager } from './memory-manager.js';
import type { Scheduler } from './scheduler.js';

function getCwd() { return process.env.CE_HUB_CWD || process.cwd(); }
function getCeHubDir() { return join(getCwd(), '.ce-hub'); }
function getWikiDir() { return '/Users/jeff/culinary-mind/wiki'; }

export async function buildApp(
  store: StateStore, engine: TaskEngine, tmux: TmuxManager,
  costTracker: CostTracker, memory: MemoryManager, scheduler: Scheduler,
) {
  const app = Fastify({ logger: true });
  const startTime = Date.now();
  await app.register(cors, { origin: true });

  // Health
  app.get('/api/health', async () => ({
    status: 'ok',
    uptime: Math.floor((Date.now() - startTime) / 1000),
    taskCount: store.countTasks(),
    queueStats: engine.getQueueStats(),
    agents: tmux.listWindows(),
    costs: costTracker.getAgentCosts(),
  }));

  // Agents
  app.get('/api/agents', async () => tmux.listWindows());

  app.post<{ Params: { name: string } }>('/api/agents/:name/start', async (req) => {
    tmux.startAgent(req.params.name);
    return { ok: true, agent: req.params.name };
  });

  app.post<{ Params: { name: string } }>('/api/agents/:name/stop', async (req) => {
    tmux.killAgent(req.params.name);
    return { ok: true };
  });

  // Tasks
  app.get('/api/tasks', async (req) => {
    const q = req.query as { status?: string; toAgent?: string };
    return store.listTasks({ status: q.status as any, to_agent: q.toAgent });
  });

  app.post('/api/tasks', async (req, reply) => {
    try {
      const b = req.body as any;
      const task = await engine.createTask({
        title: b.title, from_agent: b.fromAgent || 'api', to_agent: b.toAgent,
        depends_on: b.dependsOn, priority: b.priority, payload: b.payload,
      });
      return reply.status(201).send(task);
    } catch (e) { return reply.status(400).send({ error: String(e) }); }
  });

  app.get<{ Params: { id: string } }>('/api/tasks/:id', async (req, reply) => {
    const t = store.getTask(req.params.id);
    return t || reply.status(404).send({ error: 'Not found' });
  });

  // Events
  app.get('/api/events', async () => store.listRecentEvents());

  // Costs
  app.get('/api/costs', async () => ({
    agents: costTracker.getAgentCosts(),
    session: costTracker.getSessionCosts(),
    daily: costTracker.getPeriodCost('daily'),
    weekly: costTracker.getPeriodCost('weekly'),
  }));

  // Memory
  app.get<{ Params: { name: string } }>('/api/agents/:name/memory', async (req) => {
    return memory.getMemory(req.params.name);
  });

  // Schedules
  app.get('/api/schedules', async () => scheduler.listSchedules());

  // === Context & Wiki API ===

  // GET /api/context — compiled onboarding context for new LLM sessions
  app.get('/api/context', async () => {
    const ceHub = getCeHubDir();
    const sections: string[] = [];

    // ONBOARD.md
    const onboard = join(ceHub, 'ONBOARD.md');
    if (existsSync(onboard)) sections.push(readFileSync(onboard, 'utf-8'));

    // wiki/STATUS.md
    const status = join(getWikiDir(), 'STATUS.md');
    if (existsSync(status)) sections.push(readFileSync(status, 'utf-8'));

    return { context: sections.join('\n\n---\n\n'), files: sections.length };
  });

  // GET /api/wiki — list all wiki pages
  app.get('/api/wiki', async () => {
    const wikiDir = getWikiDir();
    if (!existsSync(wikiDir)) return { pages: [] };
    const pages: { name: string; path: string; size: number }[] = [];
    const scan = (dir: string, prefix: string) => {
      for (const f of readdirSync(dir, { withFileTypes: true })) {
        if (f.isDirectory()) scan(join(dir, f.name), `${prefix}${f.name}/`);
        else if (f.name.endsWith('.md')) {
          const full = join(dir, f.name);
          const stat = statSync(full);
          pages.push({ name: `${prefix}${f.name}`, path: `${prefix}${f.name}`, size: stat.size });
        }
      }
    };
    scan(wikiDir, '');
    return { pages };
  });

  // Safe wiki file reader — prevents path traversal
  const safeWikiRead = (subPath: string): { content: string; resolved: string } | null => {
    const wikiDir = resolve(getWikiDir());
    const target = resolve(wikiDir, subPath.endsWith('.md') ? subPath : `${subPath}.md`);
    if (!target.startsWith(wikiDir)) return null; // path traversal blocked
    if (!existsSync(target)) return null;
    return { content: readFileSync(target, 'utf-8'), resolved: target };
  };

  // GET /api/wiki/agents/:name — read agent wiki page (register BEFORE :page)
  app.get<{ Params: { name: string } }>('/api/wiki/agents/:name', async (req, reply) => {
    const result = safeWikiRead(join('agents', req.params.name));
    if (!result) return reply.status(404).send({ error: 'Agent page not found' });
    return { agent: req.params.name, content: result.content };
  });

  // GET /api/wiki/:page — read a specific wiki page
  app.get<{ Params: { page: string } }>('/api/wiki/:page', async (req, reply) => {
    const result = safeWikiRead(req.params.page);
    if (!result) return reply.status(404).send({ error: 'Page not found' });
    return { page: req.params.page, content: result.content };
  });

  // === Wiki Web Viewer (HTML) ===

  // GET /wiki/ — browse wiki in browser with markdown rendering
  app.get('/wiki', async (_req, reply) => reply.redirect('/wiki/'));
  app.get('/wiki/', async (req, reply) => {
    const wikiDir = getWikiDir();
    if (!existsSync(wikiDir)) return reply.type('text/html').send('<h1>Wiki not compiled yet</h1><p>wiki-curator agent has not run yet. Trigger via dispatch.</p>');

    // Build page list
    const pages: string[] = [];
    const scan = (dir: string, prefix: string) => {
      for (const f of readdirSync(dir, { withFileTypes: true })) {
        if (f.isDirectory()) scan(join(dir, f.name), `${prefix}${f.name}/`);
        else if (f.name.endsWith('.md')) pages.push(`${prefix}${f.name}`);
      }
    };
    scan(wikiDir, '');

    const links = pages.map(p => `<li><a href="/wiki/${p}">${p}</a></li>`).join('\n');
    reply.type('text/html').send(WIKI_INDEX_HTML.replace('{{LINKS}}', links));
  });

  // GET /wiki/:path — render wiki page as HTML
  app.get('/wiki/*', async (req, reply) => {
    const rawPath = (req.params as any)['*'] as string;
    if (!rawPath) return reply.redirect('/wiki/');
    const wikiDir = resolve(getWikiDir());
    const filePath = resolve(wikiDir, rawPath);
    if (!filePath.startsWith(wikiDir) || !existsSync(filePath)) {
      return reply.status(404).type('text/html').send('<h1>404</h1><p>Page not found</p><a href="/wiki/">← Back to wiki</a>');
    }

    const md = readFileSync(filePath, 'utf-8');
    const title = rawPath.replace('.md', '');
    const b64 = Buffer.from(md).toString('base64');
    reply.type('text/html').send(WIKI_PAGE_HTML.replace('{{TITLE}}', title).replace('{{CONTENT_B64}}', b64));
  });

  return app;
}

const WIKI_INDEX_HTML = `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CE-Hub Wiki</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #e6edf3; padding: 2rem; max-width: 800px; margin: 0 auto; }
    h1 { color: #f0883e; margin-bottom: 0.5rem; font-size: 1.5rem; }
    .subtitle { color: #7d8590; margin-bottom: 2rem; font-size: 0.875rem; }
    ul { list-style: none; }
    li { margin: 0.5rem 0; }
    a { color: #58a6ff; text-decoration: none; font-size: 1rem; padding: 0.5rem 0.75rem; display: inline-block; border-radius: 6px; transition: background 0.15s; }
    a:hover { background: #161b22; }
    .section { margin-top: 1.5rem; color: #7d8590; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
  </style>
</head>
<body>
  <h1>CE-Hub Wiki</h1>
  <p class="subtitle">Auto-compiled project knowledge — Karpathy raw/ → wiki/ model</p>
  <p class="section">Pages</p>
  <ul>
    {{LINKS}}
  </ul>
  <p style="margin-top:3rem;color:#484f58;font-size:0.75rem;">Compiled by wiki-curator agent · <a href="/api/wiki">API</a> · <a href="/api/context">Context API</a></p>
</body>
</html>`;

const WIKI_PAGE_HTML = `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{TITLE}} — CE-Hub Wiki</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"><\/script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #e6edf3; padding: 2rem; max-width: 900px; margin: 0 auto; }
    nav { margin-bottom: 1.5rem; }
    nav a { color: #58a6ff; text-decoration: none; font-size: 0.875rem; }
    #content { line-height: 1.7; }
    #content h1 { color: #f0883e; margin: 1.5rem 0 0.75rem; font-size: 1.5rem; border-bottom: 1px solid #21262d; padding-bottom: 0.5rem; }
    #content h2 { color: #e6edf3; margin: 1.25rem 0 0.5rem; font-size: 1.2rem; }
    #content h3 { color: #7d8590; margin: 1rem 0 0.5rem; }
    #content p { margin: 0.5rem 0; }
    #content table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
    #content th, #content td { border: 1px solid #30363d; padding: 0.5rem 0.75rem; text-align: left; font-size: 0.875rem; }
    #content th { background: #161b22; color: #f0883e; }
    #content tr:nth-child(even) { background: #0d1117; }
    #content tr:nth-child(odd) { background: #161b22; }
    #content code { background: #161b22; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.85rem; color: #79c0ff; }
    #content pre { background: #161b22; padding: 1rem; border-radius: 8px; overflow-x: auto; margin: 1rem 0; border: 1px solid #21262d; }
    #content pre code { background: none; padding: 0; }
    #content blockquote { border-left: 3px solid #f0883e; padding-left: 1rem; color: #7d8590; margin: 1rem 0; }
    #content ul, #content ol { margin: 0.5rem 0 0.5rem 1.5rem; }
    #content li { margin: 0.25rem 0; }
    #content a { color: #58a6ff; }
    #content hr { border: none; border-top: 1px solid #21262d; margin: 1.5rem 0; }
    .meta { color: #484f58; font-size: 0.75rem; margin-top: 2rem; }
  </style>
</head>
<body>
  <nav><a href="/wiki/">← Wiki Index</a></nav>
  <div id="content"></div>
  <p class="meta">CE-Hub Wiki · auto-compiled by wiki-curator</p>
  <script>
    const b64 = '{{CONTENT_B64}}';
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const md = new TextDecoder('utf-8').decode(bytes);
    document.getElementById('content').innerHTML = marked.parse(md);
  </script>
</body>
</html>`;
