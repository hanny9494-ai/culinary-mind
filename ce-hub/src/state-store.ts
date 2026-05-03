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

export type CcLeadSessionState = 'STARTING' | 'ACTIVE' | 'SUSPECT' | 'DEAD' | 'REPLACED';

export interface CcLeadSession {
  id: string;
  state: CcLeadSessionState;
  pid: number | null;
  wrapper_pid: number | null;
  started_at: number;
  ended_at: number | null;
  end_reason: string | null;
  last_heartbeat_at: number | null;
  recovery_summary_msg_id: string | null;
  metadata: Record<string, unknown>;
}

export interface CreateSessionInput {
  id: string;
  state?: CcLeadSessionState;
  pid?: number | null;
  wrapper_pid?: number | null;
  started_at?: number;
  metadata?: Record<string, unknown>;
}

export interface InboxMessage {
  id: string;
  file_path: string;
  target_agent: string;
  source_agent: string | null;
  type: string;
  source_task_id: string | null;
  target_session_id: string | null;
  created_at: number;
  priority: string;
  ack_required: number;
  ack_deadline_at: number | null;
  acked_at: number | null;
  acked_session_id: string | null;
  ack_outcome: string | null;
  archived_at: number | null;
  archive_dir: string | null;
  status: string;
  metadata: Record<string, unknown>;
}

export interface CreateInboxMessageInput {
  id: string;
  file_path: string;
  target_agent: string;
  source_agent?: string | null;
  type: string;
  source_task_id?: string | null;
  target_session_id?: string | null;
  created_at?: number;
  priority?: string;
  ack_required?: number;
  ack_deadline_at?: number | null;
  status?: string;
  metadata?: Record<string, unknown>;
}

function rowToSession(r: Record<string, unknown>): CcLeadSession {
  return {
    id: r.id as string,
    state: r.state as CcLeadSessionState,
    pid: (r.pid as number | null) ?? null,
    wrapper_pid: (r.wrapper_pid as number | null) ?? null,
    started_at: r.started_at as number,
    ended_at: (r.ended_at as number | null) ?? null,
    end_reason: (r.end_reason as string | null) ?? null,
    last_heartbeat_at: (r.last_heartbeat_at as number | null) ?? null,
    recovery_summary_msg_id: (r.recovery_summary_msg_id as string | null) ?? null,
    metadata: parseJson(r.metadata as string, {}),
  };
}

function rowToInboxMessage(r: Record<string, unknown>): InboxMessage {
  return {
    id: r.id as string,
    file_path: r.file_path as string,
    target_agent: r.target_agent as string,
    source_agent: (r.source_agent as string | null) ?? null,
    type: r.type as string,
    source_task_id: (r.source_task_id as string | null) ?? null,
    target_session_id: (r.target_session_id as string | null) ?? null,
    created_at: r.created_at as number,
    priority: r.priority as string,
    ack_required: r.ack_required as number,
    ack_deadline_at: (r.ack_deadline_at as number | null) ?? null,
    acked_at: (r.acked_at as number | null) ?? null,
    acked_session_id: (r.acked_session_id as string | null) ?? null,
    ack_outcome: (r.ack_outcome as string | null) ?? null,
    archived_at: (r.archived_at as number | null) ?? null,
    archive_dir: (r.archive_dir as string | null) ?? null,
    status: r.status as string,
    metadata: parseJson(r.metadata as string, {}),
  };
}

export class StateStore {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.db.pragma('busy_timeout = 10000');
    this.db.pragma('foreign_keys = ON');
    const migrationPath = resolve(__dirname, '..', 'migrations', '001_init.sql');
    this.db.exec(readFileSync(migrationPath, 'utf-8'));
    // Run additional migrations if present
    const migration2Path = resolve(__dirname, '..', 'migrations', '002_pipeline.sql');
    if (existsSync(migration2Path)) this.db.exec(readFileSync(migration2Path, 'utf-8'));
    this.initializeD68Schema();
  }

  private hasColumn(table: string, column: string): boolean {
    const rows = this.db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name: string }>;
    return rows.some((row) => row.name === column);
  }

  private initializeD68Schema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS cc_lead_sessions (
        id TEXT PRIMARY KEY,
        state TEXT NOT NULL CHECK (state IN ('STARTING','ACTIVE','SUSPECT','DEAD','REPLACED')),
        pid INTEGER,
        wrapper_pid INTEGER,
        started_at INTEGER NOT NULL,
        ended_at INTEGER,
        end_reason TEXT,
        last_heartbeat_at INTEGER,
        recovery_summary_msg_id TEXT,
        metadata TEXT NOT NULL DEFAULT '{}'
      );
      CREATE INDEX IF NOT EXISTS idx_cls_state ON cc_lead_sessions(state, started_at);
      CREATE UNIQUE INDEX IF NOT EXISTS idx_cls_one_active
        ON cc_lead_sessions(state) WHERE state = 'ACTIVE';

      CREATE TABLE IF NOT EXISTS inbox_messages (
        id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL UNIQUE,
        target_agent TEXT NOT NULL,
        source_agent TEXT,
        type TEXT NOT NULL,
        source_task_id TEXT,
        target_session_id TEXT,
        created_at INTEGER NOT NULL,
        priority TEXT NOT NULL DEFAULT 'normal',
        ack_required INTEGER NOT NULL DEFAULT 0,
        ack_deadline_at INTEGER,
        acked_at INTEGER,
        acked_session_id TEXT,
        ack_outcome TEXT,
        archived_at INTEGER,
        archive_dir TEXT,
        status TEXT NOT NULL DEFAULT 'visible',
        metadata TEXT NOT NULL DEFAULT '{}'
      );
      CREATE INDEX IF NOT EXISTS idx_inbox_target_status
        ON inbox_messages(target_agent, status, created_at);
      CREATE INDEX IF NOT EXISTS idx_inbox_unacked_overdue
        ON inbox_messages(target_agent, ack_required, acked_at, ack_deadline_at);
      CREATE INDEX IF NOT EXISTS idx_inbox_session
        ON inbox_messages(target_session_id, status);
    `);

    if (!this.hasColumn('tasks', 'result_acknowledged_at')) {
      this.db.exec('ALTER TABLE tasks ADD COLUMN result_acknowledged_at INTEGER');
    }
    if (!this.hasColumn('tasks', 'result_acknowledged_by_session_id')) {
      this.db.exec('ALTER TABLE tasks ADD COLUMN result_acknowledged_by_session_id TEXT');
    }
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_tasks_unacked
        ON tasks(status, result_acknowledged_at)
        WHERE status IN ('done','failed');
    `);
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

  // D68 cc-lead sessions
  createSession(input: CreateSessionInput): CcLeadSession {
    const row = {
      id: input.id,
      state: input.state ?? 'ACTIVE',
      pid: input.pid ?? null,
      wrapper_pid: input.wrapper_pid ?? null,
      started_at: input.started_at ?? Date.now(),
      ended_at: null,
      end_reason: null,
      last_heartbeat_at: Date.now(),
      recovery_summary_msg_id: null,
      metadata: JSON.stringify(input.metadata ?? {}),
    };
    this.db.prepare(
      `INSERT INTO cc_lead_sessions
       (id,state,pid,wrapper_pid,started_at,ended_at,end_reason,last_heartbeat_at,recovery_summary_msg_id,metadata)
       VALUES
       (@id,@state,@pid,@wrapper_pid,@started_at,@ended_at,@end_reason,@last_heartbeat_at,@recovery_summary_msg_id,@metadata)`
    ).run(row);
    const session = this.getSession(row.id);
    if (!session) throw new Error(`Failed to create session ${row.id}`);
    return session;
  }

  getSession(id: string): CcLeadSession | null {
    const row = this.db.prepare('SELECT * FROM cc_lead_sessions WHERE id = ?').get(id);
    return row ? rowToSession(row as Record<string, unknown>) : null;
  }

  getActiveSession(): CcLeadSession | null {
    const row = this.db.prepare(
      `SELECT * FROM cc_lead_sessions WHERE state = 'ACTIVE' ORDER BY started_at DESC LIMIT 1`
    ).get();
    return row ? rowToSession(row as Record<string, unknown>) : null;
  }

  markSessionEnded(id: string, endReason: string): void {
    const nextState: CcLeadSessionState = endReason === 'replaced' ? 'REPLACED' : 'DEAD';
    this.db.prepare(
      `UPDATE cc_lead_sessions
       SET state = @state, ended_at = @ended_at, end_reason = @end_reason
       WHERE id = @id AND ended_at IS NULL`
    ).run({ id, state: nextState, ended_at: Date.now(), end_reason: endReason });
  }

  updateSessionHeartbeat(id: string, pid?: number | null, wrapperPid?: number | null): void {
    this.db.prepare(
      `UPDATE cc_lead_sessions
       SET last_heartbeat_at = @last_heartbeat_at,
           pid = COALESCE(@pid, pid),
           wrapper_pid = COALESCE(@wrapper_pid, wrapper_pid),
           state = CASE WHEN state IN ('STARTING','SUSPECT') THEN 'ACTIVE' ELSE state END
       WHERE id = @id`
    ).run({ id, pid: pid ?? null, wrapper_pid: wrapperPid ?? null, last_heartbeat_at: Date.now() });
  }

  // D68 inbox tracking
  createInboxMessage(input: CreateInboxMessageInput): void {
    const row = {
      id: input.id,
      file_path: input.file_path,
      target_agent: input.target_agent,
      source_agent: input.source_agent ?? null,
      type: input.type,
      source_task_id: input.source_task_id ?? null,
      target_session_id: input.target_session_id ?? null,
      created_at: input.created_at ?? Date.now(),
      priority: input.priority ?? 'normal',
      ack_required: input.ack_required ?? 0,
      ack_deadline_at: input.ack_deadline_at ?? null,
      status: input.status ?? 'visible',
      metadata: JSON.stringify(input.metadata ?? {}),
    };
    this.db.prepare(
      `INSERT INTO inbox_messages
       (id,file_path,target_agent,source_agent,type,source_task_id,target_session_id,created_at,
        priority,ack_required,ack_deadline_at,status,metadata)
       VALUES
       (@id,@file_path,@target_agent,@source_agent,@type,@source_task_id,@target_session_id,@created_at,
        @priority,@ack_required,@ack_deadline_at,@status,@metadata)
       ON CONFLICT(id) DO UPDATE SET
        file_path=excluded.file_path,
        target_agent=excluded.target_agent,
        source_agent=excluded.source_agent,
        type=excluded.type,
        source_task_id=excluded.source_task_id,
        target_session_id=excluded.target_session_id,
        created_at=excluded.created_at,
        priority=excluded.priority,
        ack_required=excluded.ack_required,
        ack_deadline_at=excluded.ack_deadline_at,
        status=excluded.status,
        metadata=excluded.metadata`
    ).run(row);
  }

  getInboxMessage(id: string): InboxMessage | null {
    const row = this.db.prepare('SELECT * FROM inbox_messages WHERE id = ?').get(id);
    return row ? rowToInboxMessage(row as Record<string, unknown>) : null;
  }

  getInboxMessageByPath(filePath: string): InboxMessage | null {
    const normalized = filePath.replace(/\\/g, '/').replace(/^.*\.ce-hub\//, '');
    const row = this.db.prepare('SELECT * FROM inbox_messages WHERE file_path = ?').get(normalized);
    return row ? rowToInboxMessage(row as Record<string, unknown>) : null;
  }

  markInboxArchived(id: string, archiveDir: string): void {
    this.db.prepare(
      `UPDATE inbox_messages
       SET status = 'archived', archived_at = @archived_at, archive_dir = @archive_dir
       WHERE id = @id`
    ).run({ id, archived_at: Date.now(), archive_dir: archiveDir });
  }

  markInboxAcked(id: string, sessionId: string, outcome: string): void {
    this.db.prepare(
      `UPDATE inbox_messages
       SET status = 'acked', acked_at = @acked_at, acked_session_id = @acked_session_id, ack_outcome = @ack_outcome
       WHERE id = @id AND acked_at IS NULL`
    ).run({ id, acked_at: Date.now(), acked_session_id: sessionId, ack_outcome: outcome });
  }

  listVisibleInbox(agent: string, includeAckRequired = true): InboxMessage[] {
    const ackClause = includeAckRequired ? '' : 'AND ack_required = 0';
    return (this.db.prepare(
      `SELECT * FROM inbox_messages
       WHERE target_agent = @agent AND status = 'visible' ${ackClause}
       ORDER BY created_at ASC`
    ).all({ agent }) as Record<string, unknown>[]).map(rowToInboxMessage);
  }

  oldestVisibleInboxAge(agent: string, now = Date.now()): number | null {
    const row = this.db.prepare(
      `SELECT MIN(created_at) AS oldest FROM inbox_messages
       WHERE target_agent = ? AND status = 'visible'`
    ).get(agent) as { oldest: number | null } | undefined;
    if (!row?.oldest) return null;
    return Math.max(0, now - row.oldest);
  }

  markTaskResultAcknowledged(taskId: string, sessionId: string, ackedAt = Date.now()): void {
    this.db.prepare(
      `UPDATE tasks
       SET result_acknowledged_at = @acked_at,
           result_acknowledged_by_session_id = @session_id
       WHERE id = @task_id`
    ).run({ task_id: taskId, session_id: sessionId, acked_at: ackedAt });
  }

  isTaskResultAcknowledged(taskId: string): boolean {
    const row = this.db.prepare(
      `SELECT result_acknowledged_at FROM tasks WHERE id = ?`
    ).get(taskId) as { result_acknowledged_at: number | null } | undefined;
    return Boolean(row?.result_acknowledged_at);
  }

  close(): void { this.db.close(); }
}
