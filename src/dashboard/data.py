import json
import os
for _proxy_key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_proxy_key, None)

import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


API = os.environ.get("CE_HUB_API", "http://localhost:8750")
CE_HUB_CWD = Path(os.environ.get("CE_HUB_CWD", os.path.expanduser("~/culinary-mind"))).expanduser()
CE_HUB_DIR = CE_HUB_CWD / ".ce-hub"
RAW_DIR = CE_HUB_CWD / "raw"
WIKI_DIR = CE_HUB_CWD / "wiki"
BOOKS_YAML = CE_HUB_CWD / "config" / "books.yaml"
L2A_PROGRESS = CE_HUB_CWD / "output" / "l2a" / "atoms_r2" / "_progress.json"
AGENT_NAMES = [
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
PIPELINE_META: dict[str, dict[str, Any]] = {
    "l0": {
        "title": "L0 科学原理",
        "schema": "科学原理卡片: concept, mechanism, evidence, source_pages",
        "method": "Books distillation from config/books.yaml registry counts",
        "dependencies": "Source books registry, OCR/extraction outputs",
        "blockers": "Neo4j import pipeline not wired into the graph yet",
    },
    "l2b": {
        "title": "L2b 食谱",
        "schema": "Recipe objects: title, ingredients, steps, provenance",
        "method": "Book recipe extraction totals from books registry",
        "dependencies": "Recipe-capable books, step normalization stage",
        "blockers": "Step B pipeline still at zero processed recipes",
    },
    "l2a": {
        "title": "L2a 食材原子",
        "schema": "Ingredient atom: canonical_id, descriptors, sensory fields",
        "method": "R2 distillation progress from output/l2a/atoms_r2/_progress.json",
        "dependencies": "Canonical ingredient list, R2 worker batches",
        "blockers": "Full run still in progress; failures require retry sweep",
    },
    "ft": {
        "title": "FT 风味目标",
        "schema": "Flavor target vectors and target-language descriptors",
        "method": "No live producer found; placeholder stage",
        "dependencies": "L2a atoms and flavor graph alignment",
        "blockers": "No generated outputs detected",
    },
    "l6": {
        "title": "L6 翻译层",
        "schema": "User-facing semantic translation from graph to guidance",
        "method": "Pending downstream implementation",
        "dependencies": "Inference graph, prompt layer, UX surface",
        "blockers": "No translation layer outputs detected",
    },
    "external": {
        "title": "外部数据",
        "schema": "External datasets: foodb, flavorgraph, foodon, flavordb2",
        "method": "Presence inferred from local audit/report artifacts",
        "dependencies": "Open-data collector ingestion and audits",
        "blockers": "Imported status is partial and inferred from local evidence only",
    },
    "crawl": {
        "title": "全网爬取",
        "schema": "Raw crawl captures, summaries, normalized metadata",
        "method": "Recent open-data-collector crawl report activity",
        "dependencies": "Collector runs, source-site coverage, storage budget",
        "blockers": "Status inferred from recent report timestamp rather than daemon job state",
    },
    "system_y": {
        "title": "System Y",
        "schema": "Neo4j graph -> L3 agent -> baseline evaluation",
        "method": "Composite status from dependent stage availability",
        "dependencies": "Neo4j import, L3 design, baseline harness",
        "blockers": "Graph import and L3 execution remain incomplete",
    },
    "system_x": {
        "title": "System X",
        "schema": "Cluster -> templates -> prototype generation chain",
        "method": "Composite status from inferred artifact presence",
        "dependencies": "Clustering jobs, template bank, prototype UI",
        "blockers": "No completed clustering/template/prototype artifacts detected",
    },
    "user_layer": {
        "title": "User Layer",
        "schema": "L6 translation and Chainlit interaction surface",
        "method": "Composite status from l6 translation and chainlit presence",
        "dependencies": "Translation layer, app wiring, evaluation loop",
        "blockers": "Chainlit integration not found in this repo snapshot",
    },
}


@dataclass
class PipelineNodeData:
    key: str
    title: str
    summary: str
    icon: str
    style: str
    schema: str
    method: str
    dependencies: str
    blockers: str


@dataclass
class AgentMemoryStatus:
    name: str
    file_count: int
    last_output_ts: float | None
    stale: bool


@dataclass
class MemoryFileInfo:
    path: str
    modified_ts: float | None


@dataclass
class AgentStatus:
    name: str
    alive: bool | None
    status_text: str
    status_icon: str
    last_heartbeat: float | None
    current_task: str


@dataclass
class DashboardSnapshot:
    daemon_up: bool
    daemon_status_text: str
    daemon_uptime_seconds: int | None
    daemon_restart_attempts: int
    pipeline: dict[str, PipelineNodeData]
    agent_memory: list[AgentMemoryStatus]
    wiki_modified_ts: float | None
    memory_files: list[MemoryFileInfo]
    agent_statuses: list[AgentStatus]
    fetched_at: float = field(default_factory=time.time)


def fmt_count(value: int | None) -> str:
    if value is None:
        return "?"
    if value >= 1000:
        if value % 1000 == 0:
            return f"{value // 1000}K"
        return f"{value / 1000:.1f}K"
    return str(value)


def fmt_age(ts: float | None, now: float | None = None) -> str:
    if not ts:
        return "?"
    now = now or time.time()
    diff = max(0, int(now - ts))
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    return f"{diff // 86400}d ago"


def fmt_uptime(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60}m"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def api_get(path: str, timeout: float = 2.0) -> Any:
    request = urllib.request.Request(f"{API}{path}", headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        return None


def latest_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    if path.is_file():
        return path.stat().st_mtime
    latest: float | None = None
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        child_mtime = child.stat().st_mtime
        latest = child_mtime if latest is None else max(latest, child_mtime)
    return latest


def list_files(path: Path, max_depth: int = 4) -> list[Path]:
    if not path.exists():
        return []
    files: list[Path] = []
    base_depth = len(path.parts)
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        if len(child.parts) - base_depth > max_depth:
            continue
        files.append(child)
    return sorted(files)


def parse_books_registry() -> dict[str, int]:
    text = BOOKS_YAML.read_text() if BOOKS_YAML.exists() else ""
    l0_total = sum(int(value) for value in re.findall(r"^\s*l0_count:\s*(\d+)\s*$", text, re.MULTILINE))
    recipe_total = sum(int(value) for value in re.findall(r"^\s*recipe_count:\s*(\d+)\s*$", text, re.MULTILINE))
    l0_done = len(re.findall(r"^\s*l0_status:\s*done\s*$", text, re.MULTILINE))
    l0_partial = len(re.findall(r"^\s*l0_status:\s*partial\s*$", text, re.MULTILINE))
    recipe_done = len(re.findall(r"^\s*recipe_status:\s*done\s*$", text, re.MULTILINE))
    return {
        "l0_total": l0_total,
        "recipe_total": recipe_total,
        "l0_done_books": l0_done,
        "l0_partial_books": l0_partial,
        "recipe_done_books": recipe_done,
    }


def detect_external_dataset_statuses() -> dict[str, bool]:
    checks = {
        "FooDB": RAW_DIR / "coder" / "audit-foodb.md",
        "FlavorGraph": RAW_DIR / "coder" / "audit-flavorgraph.md",
        "FoodOn": RAW_DIR / "coder" / "audit-foodon.md",
        "FlavorDB2": RAW_DIR / "coder" / "audit-flavordb2.md",
    }
    return {name: path.exists() for name, path in checks.items()}


def detect_step_b_done() -> int:
    candidate_dirs = [
        CE_HUB_CWD / "output" / "l2b" / "step_b",
        CE_HUB_CWD / "output" / "recipes" / "step_b",
        CE_HUB_CWD / "data" / "l2b" / "step_b",
    ]
    for directory in candidate_dirs:
        if directory.exists():
            return len([path for path in directory.rglob("*") if path.is_file()])
    return 0


def build_pipeline_data() -> dict[str, PipelineNodeData]:
    books = parse_books_registry()
    l2a_progress = read_json(L2A_PROGRESS) or {}
    external = detect_external_dataset_statuses()
    external_bits = [f"{name} {'✅' if ok else '❌'}" for name, ok in external.items()]
    recipe_total = books["recipe_total"]
    step_b_done = detect_step_b_done()
    crawl_report = RAW_DIR / "open-data-collector" / "crawl-fullscale-progress.md"
    crawl_recent = crawl_report.exists() and (time.time() - crawl_report.stat().st_mtime) < 172800
    neo4j_ready = False
    l3_ready = (RAW_DIR / "architect" / "L3-inference-engine-design-v1.md").exists()
    baseline_ready = any(path.exists() for path in [
        RAW_DIR / "researcher" / "ragas-baseline-spec-v1.md",
        RAW_DIR / "reports" / "e2e_inference_design.md",
    ])
    cluster_ready = False
    template_ready = False
    prototype_ready = False
    chainlit_ready = any(path.name.lower().startswith("chainlit") for path in CE_HUB_CWD.glob("*"))
    l6_ready = False

    l0_summary = f"✅ {books['l0_total']:,} 条 | Neo4j: ❌"
    if books["l0_total"] == 0:
        l0_summary = "? | Neo4j: ?"

    l2b_summary = f"✅ {fmt_count(recipe_total)} | Step B: {'❌' if step_b_done == 0 else '🔄'} {step_b_done}/{fmt_count(recipe_total)}"
    if recipe_total == 0:
        l2b_summary = "? | Step B: ?"

    l2a_done = l2a_progress.get("done")
    l2a_total = l2a_progress.get("total")
    if isinstance(l2a_done, int) and isinstance(l2a_total, int) and l2a_total > 0:
        icon = "🔄" if l2a_done < l2a_total else "✅"
        l2a_summary = f"{icon} {l2a_done}/{l2a_total} | R2 status"
        l2a_style = "yellow" if l2a_done < l2a_total else "green"
    else:
        l2a_summary = "? | R2 status"
        l2a_style = "white"

    return {
        "l0": PipelineNodeData(
            key="l0",
            title=PIPELINE_META["l0"]["title"],
            summary=l0_summary,
            icon="✅" if books["l0_total"] else "?",
            style="green" if books["l0_total"] else "white",
            schema=PIPELINE_META["l0"]["schema"],
            method=PIPELINE_META["l0"]["method"],
            dependencies=PIPELINE_META["l0"]["dependencies"],
            blockers=PIPELINE_META["l0"]["blockers"],
        ),
        "l2b": PipelineNodeData(
            key="l2b",
            title=PIPELINE_META["l2b"]["title"],
            summary=l2b_summary,
            icon="✅" if recipe_total else "?",
            style="green" if recipe_total else "white",
            schema=PIPELINE_META["l2b"]["schema"],
            method=PIPELINE_META["l2b"]["method"],
            dependencies=PIPELINE_META["l2b"]["dependencies"],
            blockers=PIPELINE_META["l2b"]["blockers"],
        ),
        "l2a": PipelineNodeData(
            key="l2a",
            title=PIPELINE_META["l2a"]["title"],
            summary=l2a_summary,
            icon="🔄" if l2a_style == "yellow" else "✅" if l2a_style == "green" else "?",
            style=l2a_style,
            schema=PIPELINE_META["l2a"]["schema"],
            method=PIPELINE_META["l2a"]["method"],
            dependencies=PIPELINE_META["l2a"]["dependencies"],
            blockers=PIPELINE_META["l2a"]["blockers"],
        ),
        "ft": PipelineNodeData(
            key="ft",
            title=PIPELINE_META["ft"]["title"],
            summary="❌ 零",
            icon="❌",
            style="red",
            schema=PIPELINE_META["ft"]["schema"],
            method=PIPELINE_META["ft"]["method"],
            dependencies=PIPELINE_META["ft"]["dependencies"],
            blockers=PIPELINE_META["ft"]["blockers"],
        ),
        "l6": PipelineNodeData(
            key="l6",
            title=PIPELINE_META["l6"]["title"],
            summary="❌ 零",
            icon="❌",
            style="red",
            schema=PIPELINE_META["l6"]["schema"],
            method=PIPELINE_META["l6"]["method"],
            dependencies=PIPELINE_META["l6"]["dependencies"],
            blockers=PIPELINE_META["l6"]["blockers"],
        ),
        "external": PipelineNodeData(
            key="external",
            title=PIPELINE_META["external"]["title"],
            summary=" | ".join(external_bits) if external_bits else "?",
            icon="✅" if all(external.values()) else "🔄" if any(external.values()) else "?",
            style="green" if all(external.values()) else "yellow" if any(external.values()) else "white",
            schema=PIPELINE_META["external"]["schema"],
            method=PIPELINE_META["external"]["method"],
            dependencies=PIPELINE_META["external"]["dependencies"],
            blockers=PIPELINE_META["external"]["blockers"],
        ),
        "crawl": PipelineNodeData(
            key="crawl",
            title=PIPELINE_META["crawl"]["title"],
            summary="🔄 running" if crawl_recent else "❌ idle",
            icon="🔄" if crawl_recent else "❌",
            style="yellow" if crawl_recent else "red",
            schema=PIPELINE_META["crawl"]["schema"],
            method=PIPELINE_META["crawl"]["method"],
            dependencies=PIPELINE_META["crawl"]["dependencies"],
            blockers=PIPELINE_META["crawl"]["blockers"],
        ),
        "system_y": PipelineNodeData(
            key="system_y",
            title=PIPELINE_META["system_y"]["title"],
            summary=f"Neo4j {'❌' if not neo4j_ready else '✅'} → L3 Agent {'❌' if not l3_ready else '✅'} → Baseline {'❌' if not baseline_ready else '✅'}",
            icon="❌" if not (neo4j_ready and l3_ready and baseline_ready) else "✅",
            style="red" if not (neo4j_ready and l3_ready and baseline_ready) else "green",
            schema=PIPELINE_META["system_y"]["schema"],
            method=PIPELINE_META["system_y"]["method"],
            dependencies=PIPELINE_META["system_y"]["dependencies"],
            blockers=PIPELINE_META["system_y"]["blockers"],
        ),
        "system_x": PipelineNodeData(
            key="system_x",
            title=PIPELINE_META["system_x"]["title"],
            summary=f"聚类 {'❌' if not cluster_ready else '✅'} → 模板 {'❌' if not template_ready else '✅'} → Prototype {'❌' if not prototype_ready else '✅'}",
            icon="❌" if not (cluster_ready and template_ready and prototype_ready) else "✅",
            style="red" if not (cluster_ready and template_ready and prototype_ready) else "green",
            schema=PIPELINE_META["system_x"]["schema"],
            method=PIPELINE_META["system_x"]["method"],
            dependencies=PIPELINE_META["system_x"]["dependencies"],
            blockers=PIPELINE_META["system_x"]["blockers"],
        ),
        "user_layer": PipelineNodeData(
            key="user_layer",
            title=PIPELINE_META["user_layer"]["title"],
            summary=f"L6 翻译 {'❌' if not l6_ready else '✅'} → Chainlit {'❌' if not chainlit_ready else '✅'}",
            icon="❌" if not (l6_ready and chainlit_ready) else "✅",
            style="red" if not (l6_ready and chainlit_ready) else "green",
            schema=PIPELINE_META["user_layer"]["schema"],
            method=PIPELINE_META["user_layer"]["method"],
            dependencies=PIPELINE_META["user_layer"]["dependencies"],
            blockers=PIPELINE_META["user_layer"]["blockers"],
        ),
    }


def build_agent_memory() -> list[AgentMemoryStatus]:
    now = time.time()
    statuses: list[AgentMemoryStatus] = []
    for agent in AGENT_NAMES:
        raw_dir = RAW_DIR / agent
        files = list_files(raw_dir, max_depth=4) if raw_dir.exists() else []
        last_ts = max((path.stat().st_mtime for path in files), default=None)
        statuses.append(
            AgentMemoryStatus(
                name=agent,
                file_count=len(files),
                last_output_ts=last_ts,
                stale=(last_ts is None) or (now - last_ts > 86400),
            )
        )
    return statuses


def build_memory_files() -> list[MemoryFileInfo]:
    files = list_files(CE_HUB_DIR / "memory", max_depth=3)
    return [
        MemoryFileInfo(
            path=str(path.relative_to(CE_HUB_CWD)),
            modified_ts=path.stat().st_mtime,
        )
        for path in files[:18]
    ]


def build_agent_statuses(health: dict[str, Any] | None, task_rows: list[dict[str, Any]]) -> list[AgentStatus]:
    api_agents = {}
    if health and isinstance(health.get("agents"), list):
        for item in health["agents"]:
            if isinstance(item, dict) and item.get("name"):
                api_agents[str(item["name"])] = item

    current_task_by_agent: dict[str, str] = {}
    heartbeat_by_agent: dict[str, float | None] = {}
    active_tasks = sorted(
        (task for task in task_rows if isinstance(task, dict)),
        key=lambda task: task.get("started_at") or task.get("created_at") or task.get("completed_at") or 0,
        reverse=True,
    )
    for task in active_tasks:
        if not isinstance(task, dict):
            continue
        agent = str(task.get("to_agent") or "")
        if not agent or agent in current_task_by_agent:
            continue
        status = str(task.get("status") or "")
        if status not in {"running", "in_progress", "queued", "pending"}:
            continue
        current_task_by_agent[agent] = str(task.get("title") or "?")
        task_ts = task.get("started_at") or task.get("created_at") or task.get("completed_at")
        if isinstance(task_ts, (int, float)):
            heartbeat_by_agent[agent] = float(task_ts) / (1000.0 if task_ts > 10_000_000_000 else 1.0)

    statuses: list[AgentStatus] = []
    for agent in AGENT_NAMES:
        api_row = api_agents.get(agent, {})
        alive_raw = api_row.get("alive")
        alive = bool(alive_raw) if alive_raw is not None else None
        if alive is True:
            status_text, status_icon = "alive", "✅"
        elif alive is False:
            status_text, status_icon = "down", "❌"
        else:
            status_text, status_icon = "?", "?"
        statuses.append(
            AgentStatus(
                name=agent,
                alive=alive,
                status_text=status_text,
                status_icon=status_icon,
                last_heartbeat=heartbeat_by_agent.get(agent),
                current_task=current_task_by_agent.get(agent, "?"),
            )
        )
    return statuses


class DashboardDataSource:
    def __init__(self) -> None:
        self.restart_attempts = 0

    def collect_snapshot(self) -> DashboardSnapshot:
        health = api_get("/api/health")
        task_stats = api_get("/api/tasks/stats")
        task_rows = task_stats if isinstance(task_stats, list) else []
        if not task_rows:
            tasks_all = api_get("/api/tasks")
            if isinstance(tasks_all, list):
                task_rows = tasks_all[:200]
        daemon_up = isinstance(health, dict) and health.get("status") == "ok"
        return DashboardSnapshot(
            daemon_up=daemon_up,
            daemon_status_text="ok" if daemon_up else "DAEMON DOWN",
            daemon_uptime_seconds=int(health.get("uptime")) if daemon_up and isinstance(health.get("uptime"), int) else None,
            daemon_restart_attempts=self.restart_attempts,
            pipeline=build_pipeline_data(),
            agent_memory=build_agent_memory(),
            wiki_modified_ts=latest_mtime(WIKI_DIR),
            memory_files=build_memory_files(),
            agent_statuses=build_agent_statuses(health if isinstance(health, dict) else None, task_rows),
        )

    def send_restart_clear(self, agent_name: str) -> tuple[bool, str]:
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", f"cehub:{agent_name}.1", "/clear", "Enter"],
                cwd=str(CE_HUB_CWD),
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return True, ""
        except subprocess.CalledProcessError as exc:
            return False, exc.stderr.strip() or str(exc)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)

    def restart_daemon(self) -> tuple[bool, str]:
        ce_hub_dir = CE_HUB_CWD / "ce-hub"
        if not ce_hub_dir.exists():
            return False, f"Missing directory: {ce_hub_dir}"
        self.restart_attempts += 1
        try:
            subprocess.Popen(
                ["npm", "run", "daemon"],
                cwd=str(ce_hub_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=os.environ.copy(),
            )
            return True, ""
        except Exception as exc:
            return False, str(exc)
