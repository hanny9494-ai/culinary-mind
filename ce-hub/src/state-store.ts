import Database from 'better-sqlite3';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { v4 as uuidv4 } from 'uuid';
import type { Task, Conversation, Message, CeEvent, CreateTaskInput, TaskUpdate, TaskFilter, CreateEventInput } from './types.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function parseJson<T>(val: string | null | undefined, fallback: T): T {
  if (!val) return fallback;
  try { return JSON.parse(val) as T; } catch { return fallback; }
}

function rowToTask(r: Record<string, unknown>): Task {
  return {
    id: r.id as string, title: r.title as string,
    from_agent: r.from_agent as string, to_agent: r.to_agent as string,
    depends_on: parseJson(r.depends_on as string, []),
    status: r.status as Task['status'], priority: r.priority as number,
    model_tier: r.model_tier as Task['model_tier'],
    payload: parseJson(r.payload as string, {}),
    result: parseJson(r.result as string | null, null),
    error: (r.error as string | null) ?? null,
    retry_count: r.retry_count as number, max_retries: r.max_retries as number,
    created_at: r.created_at as number,
    started_at: (r.started_at as number | null) ?? null,
    completed_at: (r.completed_at as number | null) ?? null,
    metadata: parseJson(r.metadata as string, {}),
  };
}

function rowToEvent(r: Record<string, unknown>): CeEvent {
  return {
    id: r.id as string, type: r.type as string, source: r.source as string,
    target: (r.target as string | null) ?? null,
    payload: parseJson(r.payload as string, {}), created_at: r.created_at as number,
  };
}

export class StateStore {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.db.pragma('foreign_keys = ON');
    const migrationPath = resolve(__dirname, '..', 'migrations', '001_init.sql');
    this.db.exec(readFileSync(migrationPath, 'utf-8'));
    // Run additional migrations if present
    const migration2Path = resolve(__dirname, '..', 'migrations', '002_pipeline.sql');
    if (existsSync(migration2Path)) this.db.exec(readFileSync(migration2Path, 'utf-8'));
  }

  // Tasks
  createTask(input: CreateTaskInput): Task {
    const now = Date.now();
    const row = {
      id: input.id || uuidv4(), title: input.title, from_agent: input.from_agent, to_agent: input.to_agent,
      depends_on: JSON.stringify(input.depends_on ?? []), status: 'pending',
      priority: input.priority ?? 1, model_tier: input.model_tier ?? 'opus',
      payload: JSON.stringify(input.payload ?? {}), result: null, error: null,
      retry_count: 0, max_retries: input.max_retries ?? 3,
      created_at: now, started_at: null, completed_at: null,
      metadata: JSON.stringify(input.metadata ?? {}),
    };
    this.db.prepare(
      `INSERT INTO tasks (id,title,from_agent,to_agent,depends_on,status,priority,model_tier,payload,result,error,retry_count,max_retries,created_at,started_at,completed_at,metadata)
       VALUES (@id,@title,@from_agent,@to_agent,@depends_on,@status,@priority,@model_tier,@payload,@result,@error,@retry_count,@max_retries,@created_at,@started_at,@completed_at,@metadata)`
    ).run(row);
    return rowToTask(row as unknown as Record<string, unknown>);
  }

  getTask(id: string): Task | null {
    const r = this.db.prepare('SELECT * FROM tasks WHERE id = ?').get(id);
    return r ? rowToTask(r as Record<string, unknown>) : null;
  }

  updateTask(id: string, u: TaskUpdate): Task | null {
    const t = this.getTask(id);
    if (!t) return null;
    this.db.prepare(
      `UPDATE tasks SET status=@status, result=@result, error=@error, retry_count=@retry_count, started_at=@started_at, completed_at=@completed_at WHERE id=@id`
    ).run({
      id, status: u.status ?? t.status,
      result: u.result !== undefined ? JSON.stringify(u.result) : (t.result ? JSON.stringify(t.result) : null),
      error: u.error !== undefined ? u.error : t.error,
      retry_count: t.retry_count,
      started_at: u.started_at !== undefined ? u.started_at : t.started_at,
      completed_at: u.completed_at !== undefined ? u.completed_at : t.completed_at,
    });
    return this.getTask(id);
  }

  listTasks(filter: TaskFilter = {}): Task[] {
    return (this.db.prepare(
      `SELECT * FROM tasks WHERE (@status IS NULL OR status=@status) AND (@to_agent IS NULL OR to_agent=@to_agent) AND (@from_agent IS NULL OR from_agent=@from_agent) ORDER BY priority ASC, created_at ASC`
    ).all({ status: filter.status ?? null, to_agent: filter.to_agent ?? null, from_agent: filter.from_agent ?? null }) as Record<string, unknown>[]).map(rowToTask);
  }

  countTasks(): number {
    return (this.db.prepare('SELECT COUNT(*) as c FROM tasks').get() as { c: number }).c;
  }

  incrementTaskRetry(id: string): void {
    this.db.prepare('UPDATE tasks SET retry_count=retry_count+1 WHERE id=?').run(id);
  }

  getTasksWaitingOnDep(depId: string): Task[] {
    return (this.db.prepare(`SELECT * FROM tasks WHERE status='pending' AND depends_on LIKE ?`).all(`%${depId}%`) as Record<string, unknown>[])
      .map(rowToTask).filter(t => t.depends_on.includes(depId));
  }

  // Conversations
  getOrCreateConversation(agentName: string): string {
    const row = this.db.prepare(`SELECT id FROM conversations WHERE agent_name=? AND status='active'`).get(agentName) as { id: string } | undefined;
    if (row) return row.id;
    const id = uuidv4();
    const now = Date.now();
    this.db.prepare(`INSERT INTO conversations (id,agent_name,status,created_at,updated_at) VALUES (?,?,?,?,?)`).run(id, agentName, 'active', now, now);
    return id;
  }

  // Messages
  addMessage(agentName: string, role: string, content: string, metadata?: Record<string, unknown>): Message {
    const convId = this.getOrCreateConversation(agentName);
    const id = uuidv4();
    const now = Date.now();
    const tokenEstimate = Math.ceil(content.length / 4);
    this.db.prepare(
      `INSERT INTO messages (id,conversation_id,role,content,content_type,token_count,created_at,metadata) VALUES (?,?,?,?,?,?,?,?)`
    ).run(id, convId, role, content, 'text', tokenEstimate, now, JSON.stringify(metadata ?? {}));
    return { id, conversation_id: convId, role: role as Message['role'], content, content_type: 'text', token_count: tokenEstimate, created_at: now, metadata: metadata ?? {} };
  }

  getMessages(agentName: string, limit = 50): Message[] {
    const convId = this.getOrCreateConversation(agentName);
    const rows = this.db.prepare(
      `SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?`
    ).all(convId, limit) as Record<string, unknown>[];
    return rows.reverse().map(r => ({
      id: r.id as string, conversation_id: r.conversation_id as string,
      role: r.role as Message['role'], content: r.content as string,
      content_type: (r.content_type as string) || 'text',
      token_count: r.token_count as number | null, created_at: r.created_at as number,
      metadata: parseJson(r.metadata as string, {}),
    }));
  }

  getConversationTokenCount(agentName: string): number {
    const convId = this.getOrCreateConversation(agentName);
    const row = this.db.prepare(`SELECT SUM(token_count) as total FROM messages WHERE conversation_id=?`).get(convId) as { total: number | null };
    return row.total ?? 0;
  }

  // Summarize and archive old messages, keep recent ones
  consolidateMemory(agentName: string, summary: string, keepRecent = 10): void {
    const convId = this.getOrCreateConversation(agentName);
    const messages = this.db.prepare(`SELECT id FROM messages WHERE conversation_id=? ORDER BY created_at ASC`).all(convId) as { id: string }[];
    if (messages.length <= keepRecent + 1) return;
    const toArchive = messages.slice(0, messages.length - keepRecent);
    // Delete old messages
    const ids = toArchive.map(m => m.id);
    this.db.prepare(`DELETE FROM messages WHERE id IN (${ids.map(() => '?').join(',')})`).run(...ids);
    // Insert summary as system message
    this.addMessage(agentName, 'system', `[Memory Consolidation] ${summary}`, { type: 'memory_consolidation', archived_count: toArchive.length });
  }

  // Document tracking
  trackDocument(agentName: string, filePath: string, docType: string): void {
    this.createEvent({ type: 'document.created', source: agentName, payload: { path: filePath, doc_type: docType } });
  }

  getDocuments(agentName?: string): CeEvent[] {
    if (agentName) {
      return (this.db.prepare(`SELECT * FROM events WHERE type='document.created' AND source=? ORDER BY created_at DESC LIMIT 100`).all(agentName) as Record<string, unknown>[]).map(rowToEvent);
    }
    return (this.db.prepare(`SELECT * FROM events WHERE type='document.created' ORDER BY created_at DESC LIMIT 100`).all() as Record<string, unknown>[]).map(rowToEvent);
  }

  // Events
  createEvent(input: CreateEventInput): CeEvent {
    const row = { id: uuidv4(), type: input.type, source: input.source, target: input.target ?? null, payload: JSON.stringify(input.payload ?? {}), created_at: Date.now() };
    this.db.prepare('INSERT INTO events (id,type,source,target,payload,created_at) VALUES (@id,@type,@source,@target,@payload,@created_at)').run(row);
    return rowToEvent(row as unknown as Record<string, unknown>);
  }

  listRecentEvents(): CeEvent[] {
    return (this.db.prepare('SELECT * FROM events ORDER BY created_at DESC LIMIT 50').all() as Record<string, unknown>[]).map(rowToEvent);
  }

  close(): void { this.db.close(); }
}
