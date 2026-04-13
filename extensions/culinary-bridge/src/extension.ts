/**
 * Culinary Bridge — VS Code Extension Entry Point
 *
 * Activates on startup, starts a local HTTP server exposing the IDE's
 * built-in language models (Gemini 3.1 Pro via vscode.lm API) to
 * OpenClaw / ce-hub over HTTP.
 *
 * Endpoints exposed:
 *   GET  /health
 *   GET  /models
 *   POST /inference   { prompt, system?, model?, vendor?, stream? }
 */

import * as vscode from 'vscode';
import { CulinaryBridgeServer, ServerConfig } from './server';

let server: CulinaryBridgeServer | null = null;
let statusBarItem: vscode.StatusBarItem;

// ── Activate ──────────────────────────────────────────────────────────────────

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  console.log('[culinary-bridge] Extension activating…');

  // Status bar item
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.command = 'culinaryBridge.showStatus';
  context.subscriptions.push(statusBarItem);

  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand('culinaryBridge.showStatus', showStatus),
    vscode.commands.registerCommand('culinaryBridge.restartServer', restartServer),
  );

  // Config change listener
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsConfiguration('culinaryBridge')) {
        restartServer();
      }
    }),
  );

  // Start server on activation
  await startServer();
}

// ── Deactivate ────────────────────────────────────────────────────────────────

export async function deactivate(): Promise<void> {
  await server?.stop();
  server = null;
  console.log('[culinary-bridge] Server stopped.');
}

// ── Server lifecycle ──────────────────────────────────────────────────────────

async function startServer(): Promise<void> {
  const config = readConfig();

  if (server?.isRunning()) {
    await server.stop();
  }

  server = new CulinaryBridgeServer(config);
  try {
    await server.start();
    updateStatusBar(true, config.port);
    console.log(`[culinary-bridge] Server started on port ${config.port}`);
  } catch (e) {
    const msg = `Culinary Bridge: Failed to start on port ${config.port} — ${e}`;
    vscode.window.showErrorMessage(msg);
    updateStatusBar(false, config.port);
    console.error('[culinary-bridge]', msg);
  }
}

async function restartServer(): Promise<void> {
  await server?.stop();
  await startServer();
}

// ── Config reader ─────────────────────────────────────────────────────────────

function readConfig(): ServerConfig {
  const cfg = vscode.workspace.getConfiguration('culinaryBridge');
  return {
    port:           cfg.get<number>('port', 3456),
    token:          cfg.get<string>('bearerToken', 'culinary-bridge-local'),
    defaultVendor:  cfg.get<string>('defaultVendor', 'google'),
    defaultFamily:  cfg.get<string>('defaultFamily', 'gemini-3.1-pro'),
    timeoutMs:      cfg.get<number>('requestTimeoutMs', 120_000),
  };
}

// ── Status bar ────────────────────────────────────────────────────────────────

function updateStatusBar(running: boolean, port: number): void {
  if (running) {
    statusBarItem.text  = `$(broadcast) Bridge :${port}`;
    statusBarItem.tooltip = `Culinary Bridge running on http://127.0.0.1:${port}`;
    statusBarItem.backgroundColor = undefined;
  } else {
    statusBarItem.text  = `$(error) Bridge OFF`;
    statusBarItem.tooltip = 'Culinary Bridge is not running. Click to show status.';
    statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
  }
  statusBarItem.show();
}

// ── Status command ────────────────────────────────────────────────────────────

async function showStatus(): Promise<void> {
  const config = readConfig();
  const running = server?.isRunning() ?? false;

  let modelList = '(unknown)';
  try {
    const models = await vscode.lm.selectChatModels();
    modelList = models.length > 0
      ? models.map(m => `${m.vendor}/${m.family}@${m.version}`).join(', ')
      : '(none available)';
  } catch { /* ignore */ }

  const lines = [
    `**Culinary Bridge Status**`,
    ``,
    `Server: ${running ? `✅ running on http://127.0.0.1:${config.port}` : '❌ stopped'}`,
    `Auth:   ${config.token ? 'Bearer token configured' : '⚠️ no token (open access)'}`,
    `Model:  ${config.defaultVendor}/${config.defaultFamily}`,
    `Timeout: ${config.timeoutMs / 1000}s`,
    ``,
    `Available models: ${modelList}`,
    ``,
    `**Endpoints:**`,
    `  GET  http://127.0.0.1:${config.port}/health`,
    `  GET  http://127.0.0.1:${config.port}/models`,
    `  POST http://127.0.0.1:${config.port}/inference`,
  ];

  const action = await vscode.window.showInformationMessage(
    lines.join('\n'),
    running ? 'Restart Server' : 'Start Server',
    'Copy URL',
  );

  if (action === 'Restart Server' || action === 'Start Server') {
    await restartServer();
  } else if (action === 'Copy URL') {
    await vscode.env.clipboard.writeText(`http://127.0.0.1:${config.port}`);
  }
}
