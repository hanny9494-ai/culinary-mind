export type TaskStatus = 'pending' | 'queued' | 'running' | 'in_progress' | 'done' | 'failed' | 'dead_letter';
export type ModelTier = 'opus' | 'flash' | 'ollama';
export type MessageRole = 'user' | 'assistant' | 'system';

export interface Task {
  id: string;
  title: string;
  from_agent: string;
  to_agent: string;
  depends_on: string[];
  status: TaskStatus;
  priority: number;
  model_tier: ModelTier;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  retry_count: number;
  max_retries: number;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  metadata: Record<string, unknown>;
}

export interface Conversation {
  id: string;
  agent_name: string;
  session_id: string | null;
  status: string;
  created_at: number;
  updated_at: number;
  metadata: Record<string, unknown>;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  content_type: string;
  token_count: number | null;
  created_at: number;
  metadata: Record<string, unknown>;
}

export interface AgentSession {
  id: string;
  conversation_id: string;
  agent_name: string;
  sdk_session_id: string | null;
  pid: number | null;
  status: string;
  context_tokens: number;
  context_limit: number;
  started_at: number | null;
  stopped_at: number | null;
  last_heartbeat: number | null;
  metadata: Record<string, unknown>;
}

export interface CeEvent {
  id: string;
  type: string;
  source: string;
  target: string | null;
  payload: Record<string, unknown>;
  created_at: number;
}

export interface AgentDefinition {
  name: string;
  description: string;
  tools: string[];
  model: string;
  systemPrompt: string;
}

export interface CreateTaskInput {
  title: string;
  from_agent: string;
  to_agent: string;
  depends_on?: string[];
  priority?: number;
  model_tier?: ModelTier;
  payload?: Record<string, unknown>;
  max_retries?: number;
  metadata?: Record<string, unknown>;
}

export interface TaskUpdate {
  status?: TaskStatus;
  result?: Record<string, unknown>;
  error?: string;
  started_at?: number;
  completed_at?: number;
}

export interface TaskFilter {
  status?: TaskStatus;
  to_agent?: string;
  from_agent?: string;
}

export interface CreateEventInput {
  type: string;
  source: string;
  target?: string;
  payload?: Record<string, unknown>;
}
