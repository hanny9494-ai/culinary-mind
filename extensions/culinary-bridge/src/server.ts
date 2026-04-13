/**
 * Culinary Bridge — HTTP Server
 *
 * Exposes the VS Code LM API (Gemini 3.1 Pro, etc.) over HTTP.
 * Uses Node.js built-in `http` module — zero extra dependencies.
 *
 * Endpoints:
 *   GET  /health
 *     → { ok, server, version, model_count, uptime_ms, port }
 *
 *   GET  /models
 *     → { models: [{id, vendor, family, version, max_input_tokens}] }
 *
 *   POST /inference
 *     Request:  { prompt, system?, model?, vendor?, stream? }
 *     Response (stream=false): { text, model_used }
 *     Response (stream=true):  SSE text/event-stream
 *       data: {"type":"text","text":"..."}\n\n
 *       data: {"type":"done","model_used":"..."}\n\n
 *       data: {"type":"error","error":"..."}\n\n
 */

import * as http from 'http';
import * as vscode from 'vscode';

export interface ServerConfig {
  port: number;
  token: string;          // Bearer token; empty string = no auth check
  defaultVendor: string;  // e.g. 'google'
  defaultFamily: string;  // e.g. 'gemini-3.1-pro'
  timeoutMs: number;
}

export interface InferenceRequest {
  prompt: string;
  system?: string;
  model?: string;         // family name override (or "vendor/family")
  vendor?: string;        // vendor override
  stream?: boolean;
}

export class CulinaryBridgeServer {
  private server: http.Server | null = null;
  private startedAt = 0;
  private config: ServerConfig;

  constructor(config: ServerConfig) {
    this.config = config;
  }

  updateConfig(config: ServerConfig): void {
    this.config = config;
  }

  start(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.server = http.createServer((req, res) => {
        this._handleRequest(req, res).catch(err => {
          console.error('[culinary-bridge] Unhandled error:', err);
          if (!res.headersSent) {
            this._json(res, 500, { error: 'Internal server error' });
          }
        });
      });

      this.server.once('error', reject);

      this.server.listen(this.config.port, '127.0.0.1', () => {
        this.startedAt = Date.now();
        resolve();
      });
    });
  }

  stop(): Promise<void> {
    return new Promise((resolve) => {
      if (!this.server) { resolve(); return; }
      this.server.close(() => {
        this.server = null;
        this.startedAt = 0;
        resolve();
      });
    });
  }

  isRunning(): boolean {
    return this.server !== null && this.server.listening;
  }

  getPort(): number {
    return this.config.port;
  }

  // ── Request dispatcher ────────────────────────────────────────────────────

  private async _handleRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const url = req.url?.split('?')[0] ?? '/';
    const method = (req.method ?? 'GET').toUpperCase();

    // CORS headers on every response
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');

    if (method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

    // Auth — /health is exempt so external healthcheck probes work without token
    if (url !== '/health' && this.config.token) {
      const auth = req.headers['authorization'] ?? '';
      const tok = auth.replace(/^Bearer\s+/i, '').trim();
      if (tok !== this.config.token) {
        this._json(res, 401, { error: 'Unauthorized', detail: 'Invalid or missing Bearer token' });
        return;
      }
    }

    // Route
    if (method === 'GET' && url === '/health') {
      await this._handleHealth(res);
    } else if (method === 'GET' && url === '/models') {
      await this._handleModels(res);
    } else if (method === 'POST' && (url === '/inference' || url === '/v1/inference')) {
      await this._handleInference(req, res);
    } else {
      this._json(res, 404, { error: 'Not Found', detail: `Unknown endpoint: ${method} ${url}` });
    }
  }

  // ── GET /health ───────────────────────────────────────────────────────────

  private async _handleHealth(res: http.ServerResponse): Promise<void> {
    let modelCount = 0;
    try {
      const models = await vscode.lm.selectChatModels({});
      modelCount = models.length;
    } catch { /* ignore */ }

    this._json(res, 200, {
      ok: true,
      server: 'culinary-bridge',
      version: '0.1.0',
      model_count: modelCount,
      uptime_ms: this.startedAt ? Date.now() - this.startedAt : 0,
      port: this.config.port,
    });
  }

  // ── GET /models ───────────────────────────────────────────────────────────

  private async _handleModels(res: http.ServerResponse): Promise<void> {
    try {
      const models = await vscode.lm.selectChatModels({});
      this._json(res, 200, {
        models: models.map(m => ({
          id: m.id,
          vendor: m.vendor,
          family: m.family,
          version: m.version,
          max_input_tokens: m.maxInputTokens,
        })),
      });
    } catch (e) {
      this._json(res, 503, { error: `Failed to list models: ${e}` });
    }
  }

  // ── POST /inference ───────────────────────────────────────────────────────

  private async _handleInference(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    // Parse body
    let body: InferenceRequest;
    try {
      body = (await this._readBody(req)) as InferenceRequest;
    } catch (e) {
      this._json(res, 400, { error: 'Bad Request', detail: `Invalid JSON body: ${e}` });
      return;
    }

    if (!body.prompt || typeof body.prompt !== 'string') {
      this._json(res, 400, { error: 'Bad Request', detail: '"prompt" field is required (non-empty string)' });
      return;
    }

    // Build model selector — support "vendor/family" shorthand in model field
    let vendor = body.vendor ?? this.config.defaultVendor;
    let family = body.model ?? this.config.defaultFamily;

    if (body.model && body.model.includes('/') && !body.vendor) {
      const parts = body.model.split('/');
      vendor = parts[0];
      family = parts.slice(1).join('/');
    }

    const selector: vscode.LanguageModelChatSelector = {};
    if (vendor) { selector.vendor = vendor; }
    if (family) { selector.family = family; }

    // Model selection with graceful fallback
    let model: vscode.LanguageModelChat | undefined;
    try {
      let candidates = await vscode.lm.selectChatModels(selector);
      if (candidates.length === 0 && (selector.vendor || selector.family)) {
        // Try vendor only
        candidates = vendor ? await vscode.lm.selectChatModels({ vendor }) : [];
      }
      if (candidates.length === 0) {
        candidates = await vscode.lm.selectChatModels({});
      }
      model = candidates[0];
    } catch (e) {
      this._json(res, 503, { error: 'Failed to select models', detail: String(e) });
      return;
    }

    if (!model) {
      this._json(res, 404, {
        error: 'Model Not Found',
        detail: 'No language models available. Ensure Gemini 3.1 Pro is enabled in Antigravity.',
        hint: 'Call GET /models to see what is available.',
      });
      return;
    }

    // Build messages — embed system instructions in user turn for broadest compatibility
    const messages: vscode.LanguageModelChatMessage[] = [];
    if (body.system) {
      messages.push(
        vscode.LanguageModelChatMessage.User(
          `[SYSTEM INSTRUCTIONS]\n${body.system}\n\n[USER MESSAGE]\n${body.prompt}`
        )
      );
    } else {
      messages.push(vscode.LanguageModelChatMessage.User(body.prompt));
    }

    const cts = new vscode.CancellationTokenSource();
    const timeoutHandle = setTimeout(() => cts.cancel(), this.config.timeoutMs);
    const isStream = body.stream === true;
    const modelId = `${model.vendor}/${model.family}${model.version ? '@' + model.version : ''}`;

    try {
      const lmResponse = await model.sendRequest(messages, {}, cts.token);

      if (isStream) {
        // SSE streaming
        res.writeHead(200, {
          'Content-Type': 'text/event-stream; charset=utf-8',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
          'X-Model-Used': modelId,
        });

        // vscode.lm API: response.text is an AsyncIterable<string>
        for await (const chunk of lmResponse.text) {
          if (cts.token.isCancellationRequested) { break; }
          res.write(`data: ${JSON.stringify({ type: 'text', text: chunk })}\n\n`);
        }

        if (cts.token.isCancellationRequested) {
          res.write(`data: ${JSON.stringify({ type: 'error', error: `Timed out after ${this.config.timeoutMs}ms` })}\n\n`);
        } else {
          res.write(`data: ${JSON.stringify({ type: 'done', model_used: modelId })}\n\n`);
        }
        res.end();

      } else {
        // Collect full text
        let full = '';
        for await (const chunk of lmResponse.text) {
          full += chunk;
        }
        this._json(res, 200, { text: full, model_used: modelId });
      }

    } catch (e) {
      if (e instanceof vscode.LanguageModelError) {
        const status = e.code === 'blocked' ? 403 : 503;
        this._json(res, status, { error: `Language model error: ${e.message}`, code: e.code });
      } else if (String(e).toLowerCase().includes('cancel')) {
        this._json(res, 504, { error: 'Gateway Timeout', detail: `Inference timed out after ${this.config.timeoutMs}ms` });
      } else {
        this._json(res, 500, { error: 'Inference failed', detail: String(e) });
      }
    } finally {
      clearTimeout(timeoutHandle);
      cts.dispose();
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  private _json(res: http.ServerResponse, status: number, body: unknown): void {
    const payload = JSON.stringify(body, null, 2);
    res.writeHead(status, {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Length': Buffer.byteLength(payload),
    });
    res.end(payload);
  }

  private _readBody(req: http.IncomingMessage): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      req.on('data', (c: Buffer) => chunks.push(c));
      req.on('end', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf-8'))); }
        catch (e) { reject(e); }
      });
      req.on('error', reject);
    });
  }
}
