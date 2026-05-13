#!/usr/bin/env python3
"""Minimal Flask chat UI for culinary-mind LLM agent.

Usage:
  pip install flask
  python engine/agent/web_chat.py
  open http://localhost:5001
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask, request, jsonify, render_template_string
from engine.agent.llm_agent import answer_query

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><title>Culinary Mind 推理引擎</title>
<style>
body { font-family: -apple-system, "PingFang SC", sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; background: #1a1a1a; color: #f3efe3; }
h1 { font-size: 1.4rem; }
.subtitle { color: #888; font-size: 0.85rem; margin-bottom: 1.5rem; }
.chat { background: #252525; border-radius: 8px; padding: 1rem; min-height: 300px; max-height: 600px; overflow-y: auto; margin-bottom: 1rem; }
.msg { margin: 0.8rem 0; padding: 0.6rem 0.9rem; border-radius: 6px; font-size: 0.95rem; line-height: 1.5; }
.user { background: #003a4a; color: #66d9ff; }
.bot { background: #1a4d2e; color: #a3f7bf; white-space: pre-wrap; }
.bot .meta { color: #888; font-size: 0.75rem; margin-top: 0.5rem; }
.input-row { display: flex; gap: 0.5rem; }
input { flex: 1; padding: 0.7rem; background: #252525; color: #f3efe3; border: 1px solid #444; border-radius: 5px; font-size: 0.95rem; }
button { padding: 0.7rem 1.2rem; background: #1a4d2e; color: #a3f7bf; border: 1px solid #2a8d4e; border-radius: 5px; cursor: pointer; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.examples { color: #888; font-size: 0.8rem; margin: 0.8rem 0; }
.examples a { color: #66d9ff; cursor: pointer; margin-right: 1rem; }
</style></head>
<body>
<h1>🍳 Culinary Mind 推理引擎</h1>
<div class="subtitle">42 MF tools + 24K 食材树 + 23K 食谱 + 12K L0 因果链 + 81 PHN + 7K FT</div>

<div class="chat" id="chat"></div>

<div class="input-row">
  <input id="q" type="text" placeholder="问一个食品科学问题...(Enter 发送)" autofocus>
  <button id="send" onclick="ask()">发送</button>
</div>

<div class="examples">
  示例：
  <a onclick="setQ(this)">维生素 C 在 90°C 降解速率？A=1e10, Ea=80kJ/mol</a>
  <a onclick="setQ(this)">蛋白质 T_d=65 dH=400 在 70°C native fraction?</a>
  <a onclick="setQ(this)">2.45 GHz E=2000 ε''=15 微波吸收功率?</a>
  <a onclick="setQ(this)">25°C 纯水比热多少 Choi-Okos?</a>
</div>

<script>
const chat = document.getElementById('chat');
const q = document.getElementById('q');
const btn = document.getElementById('send');

function add(text, cls, meta) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.textContent = text;
  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta';
    m.textContent = meta;
    d.appendChild(m);
  }
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}

function setQ(el) { q.value = el.textContent; q.focus(); }

async function ask() {
  const text = q.value.trim();
  if (!text) return;
  add(text, 'user');
  q.value = '';
  btn.disabled = true; btn.textContent = '思考中...';
  try {
    const r = await fetch('/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q: text }) });
    const data = await r.json();
    const meta = data.mf_id ? `工具: ${data.mf_id} → ${data.value} ${data.unit || ''}` : '';
    add(data.answer || '(无回答)', 'bot', meta);
  } catch (e) {
    add('错误: ' + e.message, 'bot');
  } finally {
    btn.disabled = false; btn.textContent = '发送';
    q.focus();
  }
}

q.addEventListener('keydown', e => { if (e.key === 'Enter') ask(); });
</script>
</body></html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


import time as _time
import json as _json
from pathlib import Path as _Path

# Log path: output/web_chat_history.jsonl (one JSON per query)
_LOG_DIR = _Path("/Users/jeff/culinary-mind/output")
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "web_chat_history.jsonl"


def _log_query(record):
    """Append structured record to history JSONL."""
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json() or {}
    query = (data.get("q") or "").strip()
    if not query:
        return jsonify({"answer": "Empty query"})
    t0 = _time.time()
    try:
        result = answer_query(query, verbose=False)
        elapsed_s = round(_time.time() - t0, 2)
        record = {
            "ts": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            "query": query,
            "mode": result.get("mode") or ("mf_tool" if result.get("mf_id") else "unknown"),
            "mf_id": result.get("mf_id"),
            "tool_value": result.get("result", {}).get("value"),
            "tool_unit": result.get("result", {}).get("unit"),
            "tool_validity": result.get("validity"),
            "keywords": result.get("keywords"),
            "context_n": result.get("context_n"),
            "elapsed_s": elapsed_s,
            "answer_preview": (result.get("answer") or "")[:200],
        }
        _log_query(record)
        # Print to stdout so /tmp/web_chat.log captures it
        print(f"[QUERY {elapsed_s}s] mode={record['mode']} tool={record['mf_id']} ctx={record.get('context_n')} kw={record.get('keywords')}")
        print(f"  Q: {query[:120]}")
        print(f"  A: {record['answer_preview'][:120]}")
        return jsonify({
            "answer": result.get("answer", ""),
            "mf_id": result.get("mf_id"),
            "mode": result.get("mode"),
            "value": result.get("result", {}).get("value"),
            "unit": result.get("result", {}).get("unit"),
            "keywords": result.get("keywords"),
        })
    except Exception as e:
        _log_query({"ts": _time.strftime("%Y-%m-%dT%H:%M:%S"), "query": query, "error": str(e)})
        print(f"[ERROR] Q: {query[:100]} → {e}")
        return jsonify({"answer": f"Error: {e}"}), 500


@app.route("/history")
def history():
    """Browse query history JSONL."""
    items = []
    if _LOG_FILE.exists():
        for line in _LOG_FILE.read_text(encoding="utf-8").splitlines()[-50:]:
            try:
                items.append(_json.loads(line))
            except: pass
    return jsonify({"items": items, "total": len(items)})


if __name__ == "__main__":
    print("Starting Culinary Mind chat at http://localhost:5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
