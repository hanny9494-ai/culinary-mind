# Culinary Bridge

VS Code extension that exposes Antigravity's built-in Gemini 3.1 Pro (and other LM API models) as a local HTTP API. Enables OpenClaw / ce-hub to call these models programmatically without going through the UI, CDP, or any external service.

## How it works

```
OpenClaw / ce-hub  ──HTTP──→  127.0.0.1:3456  ──vscode.lm──→  Gemini 3.1 Pro (in Antigravity)
```

The extension starts a local HTTP server on activation and proxies requests to `vscode.lm.selectChatModels()` + `LanguageModelChat.sendRequest()`.

## Installation

### From source (Antigravity)

1. Open Antigravity (the VS Code fork)
2. Open this folder: `File > Open Folder… > culinary-mind/extensions/culinary-bridge`
3. Install dependencies: `npm install`
4. Compile: `npm run compile`
5. Press **F5** to launch in Extension Development Host, or run:
   ```bash
   code --extensionDevelopmentPath=$(pwd)
   ```

### Via VSIX (after packaging)

```bash
cd extensions/culinary-bridge
npm install && npm run compile
npx @vscode/vsce package
# Install the .vsix in Antigravity:
# Extensions panel → ··· → Install from VSIX…
```

## Configuration

Open Antigravity Settings (`Cmd+,`) and search **Culinary Bridge**:

| Setting | Default | Description |
|---|---|---|
| `culinaryBridge.port` | `3456` | HTTP server port. Reload window after changing. |
| `culinaryBridge.bearerToken` | `culinary-bridge-local` | Bearer token for auth. **Change this in production.** |
| `culinaryBridge.defaultVendor` | `google` | Default model vendor passed to vscode.lm selector |
| `culinaryBridge.defaultFamily` | `gemini-3.1-pro` | Default model family |
| `culinaryBridge.requestTimeoutMs` | `120000` | Max ms to wait per inference request |

## API Reference

All endpoints require `Authorization: Bearer <token>` unless token is empty.

### `GET /health`

```json
{
  "ok": true,
  "server": "culinary-bridge",
  "version": "0.1.0",
  "model_count": 2,
  "uptime_ms": 45000,
  "port": 3456
}
```

### `GET /models`

Lists all models available via `vscode.lm.selectChatModels()`.

```json
{
  "models": [
    {
      "id": "gemini-3.1-pro-20260101",
      "vendor": "google",
      "family": "gemini-3.1-pro",
      "version": "20260101",
      "max_input_tokens": 1000000
    }
  ]
}
```

### `POST /inference`

**Request:**
```json
{
  "prompt": "Extract parameters from the following text...",
  "system": "You are a food science expert...",
  "model": "gemini-3.1-pro",
  "vendor": "google",
  "stream": false
}
```

**Response (stream=false):**
```json
{
  "text": "{ \"has_formula\": true, ... }",
  "model_used": "google/gemini-3.1-pro@20260101"
}
```

**Response (stream=true):** Server-Sent Events (SSE)
```
data: {"type":"text","text":"{ \"has_formula\": "}

data: {"type":"text","text":"true, ... }"}

data: {"type":"done","model_used":"google/gemini-3.1-pro@20260101"}
```

### Error codes

| HTTP | Meaning |
|---|---|
| 401 | Invalid or missing Bearer token |
| 400 | Malformed request (missing `prompt`) |
| 403 | Model blocked the request (safety filter) |
| 503 | No models available or model selection failed |
| 504 | Request timed out |
| 500 | Internal server error |

## Usage from ce-hub / OpenClaw

```typescript
// Example: call /inference from ce-hub
const resp = await fetch('http://127.0.0.1:3456/inference', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer culinary-bridge-local',
  },
  body: JSON.stringify({
    prompt: skillPrompt + '\n\n' + chunkText,
    model: 'gemini-3.1-pro',
    stream: false,
  }),
});
const { text, model_used } = await resp.json();
```

## Status bar

When active, the extension shows **`⊕ Bridge :3456`** in the status bar (bottom right). Click it to see status, available models, and restart the server.

## Commands

- `Culinary Bridge: Show Server Status` — opens an info panel with full status
- `Culinary Bridge: Restart HTTP Server` — restarts the HTTP server (useful after config changes)

## Troubleshooting

**Server doesn't start:**
- Check if port 3456 is already in use: `lsof -i :3456`
- Change `culinaryBridge.port` in settings

**No models available (503):**
- Ensure Gemini 3.1 Pro is activated in Antigravity
- Check `GET /models` response — if empty, the VS Code LM API has no registered models

**`vscode.lm` is undefined:**
- This extension requires VS Code ≥ 1.99.0 or Antigravity's equivalent fork
- Check `engines.vscode` in package.json matches your Antigravity version

## Security

- The server only binds to `127.0.0.1` (localhost), never exposed to network
- Bearer token auth is required by default (`culinary-bridge-local`)
- Change the token in settings if running on a shared machine
