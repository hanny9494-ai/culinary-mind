#!/usr/bin/env python3
"""
CC Switch Web UI — 在浏览器里管理 Claude Code API providers。
Usage: python3 scripts/ccs_web.py   → 打开 http://localhost:9090
"""

import json
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PORT = 7777
CCS_STORE = Path.home() / ".cc-switch" / "configs.json"
SETTINGS = Path.home() / ".claude" / "settings.json"


def load_configs():
    if not CCS_STORE.exists():
        return {}, ""
    data = json.loads(CCS_STORE.read_text())
    configs = {c["name"]: c for c in data.get("configs", [])}
    current = data.get("currentConfig", "")
    return configs, current


HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>CC Switch</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0d1117; color: #e6edf3; padding: 32px; }
h1 { font-size: 20px; margin-bottom: 24px; color: #58a6ff; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; display: flex; align-items: center; gap: 16px; }
.card.active { border-color: #238636; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: #30363d; flex-shrink: 0; }
.dot.on { background: #3fb950; }
.info { flex: 1; }
.name { font-size: 16px; font-weight: 600; }
.url { font-size: 12px; color: #8b949e; margin-top: 4px; }
.badge { font-size: 11px; background: #238636; color: #fff; padding: 2px 8px; border-radius: 12px; margin-left: 8px; }
button { padding: 6px 16px; border-radius: 6px; border: 1px solid #30363d; background: #21262d; color: #e6edf3; cursor: pointer; font-size: 13px; }
button:hover { background: #30363d; }
button.switch-btn { background: #1f6feb; border-color: #1f6feb; }
button.switch-btn:hover { background: #388bfd; }
.add-form { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-top: 24px; }
.add-form h2 { font-size: 15px; margin-bottom: 16px; color: #8b949e; }
input { background: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #e6edf3; padding: 6px 10px; font-size: 13px; width: 100%; margin-bottom: 10px; }
input:focus { outline: none; border-color: #58a6ff; }
.row { display: flex; gap: 8px; }
.row input { margin-bottom: 0; }
#msg { margin-top: 12px; font-size: 13px; color: #3fb950; min-height: 20px; }
</style>
</head>
<body>
<h1>⚡ CC Switch</h1>
<div id="list">Loading...</div>
<div class="add-form">
  <h2>Add Provider</h2>
  <input id="aname" placeholder="Name (e.g. anthropic, lingya, openrouter)">
  <input id="aurl" placeholder="Base URL (e.g. https://api.anthropic.com)">
  <input id="atoken" placeholder="API Token" type="password">
  <button onclick="addProvider()">Add</button>
  <div id="msg"></div>
</div>
<script>
async function load() {
  const r = await fetch('/api/list');
  const d = await r.json();
  const el = document.getElementById('list');
  if (!d.configs || Object.keys(d.configs).length === 0) {
    el.innerHTML = '<p style="color:#8b949e">No providers configured.</p>';
    return;
  }
  el.innerHTML = Object.entries(d.configs).map(([name, cfg]) => {
    const active = name === d.current;
    const url = cfg.url || cfg.baseUrl || '';
    return `<div class="card ${active ? 'active' : ''}">
      <div class="dot ${active ? 'on' : ''}"></div>
      <div class="info">
        <div class="name">${name}${active ? '<span class="badge">ACTIVE</span>' : ''}</div>
        <div class="url">${url}</div>
      </div>
      ${active ? '' : `<button class="switch-btn" onclick="sw('${name}')">Switch</button>`}
      <button onclick="rm('${name}')">Remove</button>
    </div>`;
  }).join('');
}
async function sw(name) {
  await fetch('/api/switch', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})});
  load();
}
async function rm(name) {
  if (!confirm('Remove ' + name + '?')) return;
  await fetch('/api/remove', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})});
  load();
}
async function addProvider() {
  const name = document.getElementById('aname').value.trim();
  const url = document.getElementById('aurl').value.trim();
  const token = document.getElementById('atoken').value.trim();
  if (!name || !url || !token) { document.getElementById('msg').textContent = 'All fields required'; return; }
  const r = await fetch('/api/add', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, url, token})});
  const d = await r.json();
  document.getElementById('msg').textContent = d.ok ? '✅ Added' : '❌ ' + d.error;
  if (d.ok) { document.getElementById('aname').value=''; document.getElementById('aurl').value=''; document.getElementById('atoken').value=''; load(); }
}
load();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == "/api/list":
            configs, current = load_configs()
            self._json(200, {"configs": configs, "current": current})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/switch":
            name = body.get("name", "")
            r = subprocess.run(["ccs", "switch", name], capture_output=True, text=True)
            self._json(200, {"ok": r.returncode == 0, "out": r.stdout})

        elif self.path == "/api/remove":
            name = body.get("name", "")
            r = subprocess.run(["ccs", "remove", name], capture_output=True, text=True, input="y\n")
            self._json(200, {"ok": r.returncode == 0})

        elif self.path == "/api/add":
            name = body.get("name", "")
            url = body.get("url", "")
            token = body.get("token", "")
            r = subprocess.run(["ccs", "add", name, url, token], capture_output=True, text=True)
            self._json(200, {"ok": r.returncode == 0, "error": r.stderr[:100]})

        else:
            self._json(404, {"error": "not found"})

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    import webbrowser
    print(f"CC Switch Web UI → http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
