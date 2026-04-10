"""
data.py — culinary-mind dashboard data fetching layer.
Daemon API (localhost:8750) + filesystem scans.
No proxy usage: all connections are local.
"""

import os
import time
import urllib.request
import urllib.error
import json
import glob
from dataclasses import dataclass, field
from typing import Optional

# Clear proxy env vars — local-only connections
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

CE_HUB_CWD = os.environ.get("CE_HUB_CWD", os.path.expanduser("~/culinary-mind"))
DAEMON_API = os.environ.get("CE_HUB_API", "http://localhost:8750")

# Daemon restart command
DAEMON_RESTART_CMD = f"cd {CE_HUB_CWD}/ce-hub && npm run daemon"

AGENTS = [
    "cc-lead",
    "coder",
    "researcher",
    "architect",
    "pipeline-runner",
    "code-reviewer",
    "ops",
    "open-data-collector",
    "wiki-curator",
]


# ── HTTP helper ────────────────────────────────────────────────────────────────

def _api_get(path: str, timeout: float = 2.0) -> Optional[dict]:
    """GET from daemon API. Returns None on any error."""
    try:
        handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(
            f"{DAEMON_API}{path}",
            headers={"Accept": "application/json"},
        )
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class DaemonHealth:
    online: bool = False
    uptime_s: int = 0
    task_count: int = 0
    queue_stats: dict = field(default_factory=dict)
    agents: list = field(default_factory=list)

    @property
    def uptime_str(self) -> str:
        s = self.uptime_s
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m{s % 60}s"
        return f"{s // 3600}h{(s % 3600) // 60}m"


@dataclass
class AgentStatus:
    name: str
    alive: bool = False
    last_heartbeat_ago: str = "?"
    current_task: str = "—"


@dataclass
class AgentMemory:
    name: str
    file_count: int = 0
    last_write_ago: str = "never"
    last_write_ts: float = 0.0
    stale: bool = False  # > 24h


@dataclass
class PipelineNode:
    key: str
    label: str
    status: str      # "ok" | "error" | "progress" | "pending"
    detail: str = ""
    count: Optional[int] = None
    children: list = field(default_factory=list)


# ── Fetchers ───────────────────────────────────────────────────────────────────

def fetch_health() -> DaemonHealth:
    data = _api_get("/api/health")
    if data is None:
        return DaemonHealth(online=False)
    return DaemonHealth(
        online=True,
        uptime_s=int(data.get("uptime", 0)),
        task_count=int(data.get("taskCount", 0)),
        queue_stats=data.get("queueStats", {}),
        agents=data.get("agents", []),
    )


def fetch_agents(health: Optional[DaemonHealth] = None) -> list[AgentStatus]:
    if health is None:
        health = fetch_health()
    alive_map = {a["name"]: a.get("alive", False) for a in health.agents}
    result = []
    for name in AGENTS:
        result.append(AgentStatus(
            name=name,
            alive=alive_map.get(name, False),
        ))
    return result


def _scan_dir_recency(path: str) -> tuple[int, float]:
    """Return (file_count, latest_mtime) for all files under path."""
    if not os.path.isdir(path):
        return 0, 0.0
    files = glob.glob(os.path.join(path, "**", "*"), recursive=True)
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        return 0, 0.0
    latest = max(os.path.getmtime(f) for f in files)
    return len(files), latest


def _ago_str(ts: float) -> str:
    if ts == 0:
        return "never"
    diff = time.time() - ts
    if diff < 60:
        return f"{int(diff)}s ago"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    return f"{int(diff // 86400)}d ago"


def fetch_memory() -> list[AgentMemory]:
    result = []
    now = time.time()
    for name in AGENTS:
        raw_path = os.path.join(CE_HUB_CWD, "raw", name)
        count, latest = _scan_dir_recency(raw_path)
        stale = (now - latest > 86400) if latest > 0 else True
        result.append(AgentMemory(
            name=name,
            file_count=count,
            last_write_ago=_ago_str(latest),
            last_write_ts=latest,
            stale=stale,
        ))
    return result


def fetch_wiki_mtime() -> str:
    wiki_path = os.path.join(CE_HUB_CWD, "wiki")
    _, latest = _scan_dir_recency(wiki_path)
    return _ago_str(latest)


def fetch_memory_files() -> list[tuple[str, str]]:
    """Return list of (filename, ago_str) from .ce-hub/memory/"""
    mem_path = os.path.join(CE_HUB_CWD, ".ce-hub", "memory")
    if not os.path.isdir(mem_path):
        return []
    files = sorted(glob.glob(os.path.join(mem_path, "*")))
    result = []
    for f in files:
        name = os.path.basename(f)
        mtime = os.path.getmtime(f)
        result.append((name, _ago_str(mtime)))
    return result


# ── Pipeline state ─────────────────────────────────────────────────────────────

def _count_files(path: str, pattern: str = "**/*") -> int:
    if not os.path.isdir(path):
        return 0
    return len([f for f in glob.glob(os.path.join(path, pattern), recursive=True)
                if os.path.isfile(f)])


def _dir_exists(path: str) -> bool:
    return os.path.isdir(path)


def _file_exists(path: str) -> bool:
    return os.path.isfile(path)


def fetch_pipeline_state() -> dict:
    """Scan filesystem to determine pipeline component statuses."""
    out = os.path.join(CE_HUB_CWD, "output")
    data_ext = os.path.join(CE_HUB_CWD, "data", "external")

    # L0 knowledge nodes
    l0_count = _count_files(os.path.join(out, "l0_nodes"), "*.jsonl")
    if l0_count == 0:
        l0_jsonl = _count_files(os.path.join(out, "stage4"), "*.jsonl")
        l0_count = l0_jsonl

    # L2b recipes
    l2b_count = _count_files(os.path.join(out, "recipes"), "*.jsonl")
    if l2b_count == 0:
        l2b_count = _count_files(os.path.join(out, "stage5"), "*.jsonl")

    # L2a distilled items
    l2a_path = os.path.join(out, "l2a")
    l2a_count = _count_files(l2a_path, "*.jsonl")

    # External data presence
    foodb_ok = _dir_exists(os.path.join(data_ext, "foodb"))
    flavorgraph_ok = _dir_exists(os.path.join(data_ext, "flavorgraph")) or \
                     _dir_exists(os.path.join(data_ext, "raw", "flavorgraph"))
    foodon_ok = _dir_exists(os.path.join(data_ext, "foodon")) or \
                _dir_exists(os.path.join(data_ext, "raw", "foodon"))
    flavordb2_ok = _dir_exists(os.path.join(data_ext, "flavordb2")) or \
                   _dir_exists(os.path.join(data_ext, "raw", "flavordb2"))

    # Neo4j: check import progress file
    neo4j_import_file = os.path.join(CE_HUB_CWD, "scripts", "y_s1", "l0_neo4j_progress.json")
    neo4j_count = 0
    if os.path.isfile(neo4j_import_file):
        try:
            with open(neo4j_import_file) as f:
                neo4j_data = json.load(f)
                neo4j_count = neo4j_data.get("imported", 0)
        except Exception:
            pass

    return {
        "l0_count": l0_count,
        "l0_ok": l0_count > 1000,
        "neo4j_count": neo4j_count,
        "neo4j_ok": neo4j_count > 10000,
        "l2b_count": l2b_count,
        "l2b_ok": l2b_count > 1000,
        "l2a_count": l2a_count,
        "l2a_ok": l2a_count > 0,
        "ft_ok": False,   # not yet built
        "l6_ok": False,   # not yet built
        "foodb_ok": foodb_ok,
        "flavorgraph_ok": flavorgraph_ok,
        "foodon_ok": foodon_ok,
        "flavordb2_ok": flavordb2_ok,
        "pass1_ok": False,  # not yet built
        "system_y_ok": False,
        "system_x_ok": False,
        "chainlit_ok": False,
    }
