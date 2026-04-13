/**
 * AntigravityStream — WebSocket 实时监听客户端
 *
 * 连接 ws://localhost:9812，保持长连接复用，
 * 实时接收 Antigravity 的处理结果回调。
 *
 * 用法：
 *   const stream = AntigravityStream.getInstance();
 *   await stream.connect();
 *   stream.on('chunk_id', (msg) => { ... });
 *   stream.waitForResult('chunk_id', 120_000).then(result => { ... });
 */

import { WebSocket } from 'ws';
import { EventEmitter } from 'node:events';

const WS_URL = process.env.ANTIGRAVITY_WS || 'ws://localhost:9812';
const RECONNECT_DELAY_MS = 3_000;
const MAX_RECONNECT_ATTEMPTS = 5;

export interface AntigravityMessage {
  type?: string;           // 'chunk_result' | 'batch_done' | 'error' | 'ping' | string
  chunk_id?: string;
  batch_id?: string;
  content?: string;        // raw text from Antigravity
  result_path?: string;    // path to result file if Antigravity wrote one
  status?: 'ok' | 'error' | 'partial';
  error?: string;
  [key: string]: unknown;
}

export class AntigravityStream extends EventEmitter {
  private static instance: AntigravityStream | null = null;

  private ws: WebSocket | null = null;
  private connected = false;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingWaiters = new Map<string, {
    resolve: (msg: AntigravityMessage) => void;
    reject: (err: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  }>();

  private constructor() {
    super();
  }

  static getInstance(): AntigravityStream {
    if (!AntigravityStream.instance) {
      AntigravityStream.instance = new AntigravityStream();
    }
    return AntigravityStream.instance;
  }

  // ── Connection ─────────────────────────────────────────────────────────────

  async connect(): Promise<void> {
    if (this.connected && this.ws?.readyState === WebSocket.OPEN) return;

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(WS_URL);
      const connectTimeout = setTimeout(() => {
        ws.terminate();
        reject(new Error(`AntigravityStream: connect timeout to ${WS_URL}`));
      }, 8_000);

      ws.on('open', () => {
        clearTimeout(connectTimeout);
        this.ws = ws;
        this.connected = true;
        this.reconnectAttempts = 0;
        console.error(`[antigravity-stream] Connected to ${WS_URL}`);
        this.emit('connected');
        resolve();
      });

      ws.on('message', (data: Buffer | string) => {
        this._handleMessage(data.toString());
      });

      ws.on('close', (code, reason) => {
        this.connected = false;
        this.ws = null;
        console.error(`[antigravity-stream] Disconnected (${code} ${reason}). Scheduling reconnect...`);
        this.emit('disconnected', code);
        this._scheduleReconnect();
      });

      ws.on('error', (err) => {
        clearTimeout(connectTimeout);
        console.error(`[antigravity-stream] WebSocket error: ${err.message}`);
        this.emit('error', err);
        if (!this.connected) {
          reject(err);
        }
      });

      ws.on('ping', () => ws.pong());
    });
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectAttempts = MAX_RECONNECT_ATTEMPTS; // stop auto-reconnect
    this.ws?.close();
    this.ws = null;
    this.connected = false;
  }

  isConnected(): boolean {
    return this.connected && this.ws?.readyState === WebSocket.OPEN;
  }

  // ── Message handler ────────────────────────────────────────────────────────

  private _handleMessage(raw: string): void {
    let msg: AntigravityMessage;
    try {
      msg = JSON.parse(raw);
    } catch {
      // Plain text output — wrap it
      msg = { type: 'text', content: raw };
    }

    // Emit to generic listeners
    this.emit('message', msg);

    // Resolve waiter if chunk_id matches
    if (msg.chunk_id) {
      const waiter = this.pendingWaiters.get(msg.chunk_id);
      if (waiter) {
        clearTimeout(waiter.timer);
        this.pendingWaiters.delete(msg.chunk_id);
        waiter.resolve(msg);
      }
      this.emit(`chunk:${msg.chunk_id}`, msg);
    }

    // Batch done — resolve all pending waiters for this batch
    if (msg.batch_id && msg.type === 'batch_done') {
      this.emit(`batch:${msg.batch_id}`, msg);
    }

    // Handle ping/pong
    if (msg.type === 'ping') {
      this.ws?.send(JSON.stringify({ type: 'pong' }));
    }
  }

  // ── Waiter API ─────────────────────────────────────────────────────────────

  /**
   * Wait for a specific chunk_id result to arrive over WebSocket.
   * Returns the message, or rejects on timeout.
   */
  waitForResult(chunkId: string, timeoutMs: number): Promise<AntigravityMessage> {
    return new Promise((resolve, reject) => {
      // Check if already received (race condition guard)
      const timer = setTimeout(() => {
        this.pendingWaiters.delete(chunkId);
        reject(new Error(`AntigravityStream: timeout waiting for chunk_id=${chunkId} after ${timeoutMs}ms`));
      }, timeoutMs);

      this.pendingWaiters.set(chunkId, { resolve, reject, timer });
    });
  }

  /**
   * Wait for a batch_id to complete.
   */
  waitForBatch(batchId: string, timeoutMs: number): Promise<AntigravityMessage> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.removeAllListeners(`batch:${batchId}`);
        reject(new Error(`AntigravityStream: timeout waiting for batch_id=${batchId}`));
      }, timeoutMs);

      this.once(`batch:${batchId}`, (msg: AntigravityMessage) => {
        clearTimeout(timer);
        resolve(msg);
      });
    });
  }

  // ── Reconnect ──────────────────────────────────────────────────────────────

  private _scheduleReconnect(): void {
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.error('[antigravity-stream] Max reconnect attempts reached. Giving up.');
      return;
    }
    this.reconnectAttempts++;
    const delay = RECONNECT_DELAY_MS * this.reconnectAttempts;
    console.error(`[antigravity-stream] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`);
    this.reconnectTimer = setTimeout(() => {
      this.connect().catch(err => {
        console.error(`[antigravity-stream] Reconnect failed: ${err.message}`);
      });
    }, delay);
  }
}
