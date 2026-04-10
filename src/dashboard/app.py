#!/usr/bin/env python3
"""
culinary-mind Textual Dashboard
Replace watch+bash with a zero-flicker Textual TUI.

Usage:
    python3 src/dashboard/app.py                    # global view (cc-lead)
    python3 src/dashboard/app.py --agent=coder      # agent-specific view
    python3 src/dashboard/app.py --global           # explicit global

Requires: pip install textual
"""

import os
import sys
import time
import argparse
import subprocess
import threading

# Clear proxy env vars — all connections are local
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

CE_HUB_CWD = os.environ.get("CE_HUB_CWD", os.path.expanduser("~/culinary-mind"))

# Path shim: ensure repo root on sys.path for absolute imports
_repo_root = CE_HUB_CWD
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# ── Textual availability check ─────────────────────────────────────────────────
try:
    from textual.app import App, ComposeResult
    from textual.widgets import Header, Footer, Static, Label, Tree, DataTable, Button
    from textual.containers import Horizontal, Vertical, ScrollableContainer
    from textual.reactive import reactive
    from textual import on
    from textual.timer import Timer
    _TEXTUAL_OK = True
except ImportError:
    _TEXTUAL_OK = False


# ── Fallback: no textual ───────────────────────────────────────────────────────
def _fallback_run() -> None:
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  culinary-mind dashboard — textual not installed         ║")
    print("║                                                          ║")
    print("║  Run:  pip install textual                               ║")
    print("║  Then: python3 src/dashboard/app.py                     ║")
    print("╚══════════════════════════════════════════════════════════╝")
    sys.exit(1)


# ── Daemon watchdog ────────────────────────────────────────────────────────────
DAEMON_FAIL_COUNT = 0
DAEMON_RESTART_CMD = f"cd {CE_HUB_CWD}/ce-hub && npm run daemon"


def _restart_daemon() -> None:
    """Attempt to restart the daemon in background."""
    subprocess.Popen(
        DAEMON_RESTART_CMD,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ── CSS ────────────────────────────────────────────────────────────────────────
CSS = """
Screen {
    layers: base;
    background: $surface;
}

#header-bar {
    height: 3;
    background: $primary-darken-2;
    padding: 0 2;
    align: left middle;
}

#daemon-status {
    width: auto;
    margin-right: 2;
    content-align: left middle;
}

#header-info {
    width: 1fr;
    content-align: right middle;
    color: $text-muted;
}

#main-layout {
    height: 1fr;
}

#left-panel {
    width: 2fr;
    height: 1fr;
    border: round $accent;
    padding: 0 1;
}

#right-panel {
    width: 1fr;
    height: 1fr;
    border: round $accent;
    padding: 0 1;
}

#bottom-panel {
    height: auto;
    max-height: 16;
    border: round $accent;
    padding: 0 1;
}

#pipeline-tree {
    height: 1fr;
    overflow-y: auto;
}

#memory-table {
    height: 1fr;
    overflow-y: auto;
}

#agent-table {
    height: auto;
    overflow-y: auto;
}

.panel-title {
    text-style: bold;
    color: $accent;
    height: 1;
    padding: 0 0 1 0;
}

#restart-all-row {
    height: 3;
    align: right middle;
}

Button {
    min-width: 9;
    height: 1;
    margin: 0;
}

.daemon-up { color: $success; }
.daemon-down { color: $error; text-style: bold; }
"""


# ── Main App ───────────────────────────────────────────────────────────────────
if _TEXTUAL_OK:
    from src.dashboard.data import (
        fetch_health, fetch_agents, fetch_memory, fetch_wiki_mtime,
        fetch_memory_files, fetch_pipeline_state, AGENTS, DaemonHealth,
        _ago_str, _scan_dir_recency, CE_HUB_CWD as DATA_CE_HUB_CWD,
    )

    _restarting: dict[str, float] = {}
    TMUX_SESSION = "cehub"

    class CulinaryDashboard(App):
        CSS = CSS
        TITLE = "culinary-mind"
        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
        ]

        _daemon_ok: reactive[bool] = reactive(True)
        _daemon_fail_count: reactive[int] = reactive(0)
        _uptime_str: reactive[str] = reactive("—")
        _task_count: reactive[int] = reactive(0)

        def __init__(self, agent: str = "global"):
            super().__init__()
            self._agent = agent
            self._last_health: DaemonHealth | None = None

        def compose(self) -> ComposeResult:
            # Header bar
            with Horizontal(id="header-bar"):
                yield Label("", id="daemon-status")
                yield Label("", id="header-info")

            # Main: left (pipeline tree) + right (memory)
            with Horizontal(id="main-layout"):
                with ScrollableContainer(id="left-panel"):
                    yield Static("📦 Project Pipeline", classes="panel-title")
                    yield Tree("🍳 culinary-mind", id="pipeline-tree")
                with ScrollableContainer(id="right-panel"):
                    yield Static("📝 Memory Recency", classes="panel-title")
                    yield DataTable(id="memory-table", show_cursor=False)

            # Bottom: agent panel
            with Vertical(id="bottom-panel"):
                with Horizontal(id="restart-all-row"):
                    yield Static("🤖 Agent Status", classes="panel-title")
                    yield Button("↺ Restart All", id="restart-all", variant="warning")
                yield DataTable(id="agent-table", show_cursor=False)

            yield Footer()

        def on_mount(self) -> None:
            # Memory table columns
            mem_table = self.query_one("#memory-table", DataTable)
            mem_table.add_columns("Agent", "Files", "Last Write")

            # Agent table columns
            agent_table = self.query_one("#agent-table", DataTable)
            agent_table.add_columns("Agent", "Status", "Heartbeat", "")

            # Pipeline tree
            tree = self.query_one("#pipeline-tree", Tree)
            tree.root.expand()

            # Initial data load
            self._do_full_refresh()

            # Timers
            self.set_interval(10, self._refresh_pipeline)
            self.set_interval(30, self._refresh_memory)
            self.set_interval(10, self._refresh_agents)
            self.set_interval(60, self._check_daemon)

        # ── Daemon check ───────────────────────────────────────────────────────

        def _check_daemon(self) -> None:
            health = fetch_health()
            if not health.online:
                self._daemon_fail_count += 1
                self._daemon_ok = False
                if self._daemon_fail_count >= 3:
                    _restart_daemon()
                    self._daemon_fail_count = 0
            else:
                self._daemon_fail_count = 0
                self._daemon_ok = True
                self._last_health = health
                self._uptime_str = health.uptime_str
                self._task_count = health.task_count
            self._update_header()

        def _update_header(self) -> None:
            ds = self.query_one("#daemon-status", Label)
            hi = self.query_one("#header-info", Label)
            now = time.strftime("%H:%M:%S")

            if self._daemon_ok:
                ds.update(f"[green]● daemon up[/green]  uptime: {self._uptime_str}  tasks: {self._task_count}")
            else:
                fails = self._daemon_fail_count
                ds.update(f"[red bold]⚠ DAEMON DOWN[/red bold]  (failures: {fails})")

            agent_label = f"agent: {self._agent}" if self._agent != "global" else "global view"
            hi.update(f"{now}  |  {agent_label}")

        # ── Pipeline tree ──────────────────────────────────────────────────────

        def _refresh_pipeline(self) -> None:
            tree = self.query_one("#pipeline-tree", Tree)
            tree.clear()
            state = fetch_pipeline_state()
            self._build_pipeline_tree(tree.root, state)
            tree.root.expand()

        def _build_pipeline_tree(self, root, state: dict) -> None:
            def s(ok: bool, prog: bool = False) -> str:
                if prog:
                    return "🔄"
                return "✅" if ok else "❌"

            # ── TIER 1 ────────────────────────────────────────────────────────
            t1 = root.add("📦 Tier 1 — Data Distillation", expand=True)

            l0_node = t1.add(
                f"{s(state['l0_ok'])} L0 科学原理  {state['l0_count']:,} 条"
                f"  |  Neo4j: {s(state['neo4j_ok'], state['neo4j_count'] > 0 and not state['neo4j_ok'])} {state['neo4j_count']:,}",
                expand=False,
            )
            l0_node.add_leaf("17 domains: protein_science / thermal_dynamics / fermentation / …")
            l0_node.add_leaf("Blocker: Neo4j re-import with Gemini 3072-dim embeddings (PR #13)")

            l2b_node = t1.add(
                f"{s(state['l2b_ok'])} L2b 食谱校准库  {state['l2b_count']:,} 条"
                f"  |  Step B (L0 binding): ❌",
                expand=False,
            )
            l2b_node.add_leaf("Step A complete: 29K+ recipes from 63 books")
            l2b_node.add_leaf("Step B pending: L0 domain tagging + parameter binding")

            l2a_node = t1.add(
                f"{s(state['l2a_ok'], state['l2a_count'] > 0)} L2a 食材原子库  {state['l2a_count']:,} 条"
                f"  |  R2 蒸馏: {'🔄 running' if state['l2a_count'] > 0 else '❌'}",
                expand=False,
            )
            l2a_node.add_leaf("distill_r2.py → Lingya gemini-3-flash-preview-search")

            t1.add("❌ FT 风味目标库  0 条  |  依赖 Pass 1 (prompt 未设计)").add_leaf(
                "Source: FlavorDB2 596 descriptors + Pass1 multi-task"
            )
            t1.add("❌ L6 翻译层  0 条  |  依赖 Pass 1").add_leaf(
                "Cantonese aesthetic vocabulary ↔ system language"
            )
            t1.add("❌ Pass 1 一石多鸟  |  prompt 待设计")

            ext = t1.add("🗄️  外部数据 (read-only audit done)", expand=False)
            ext.add_leaf(f"{'✅' if state['foodb_ok'] else '❌'} FooDB       1,342 foods / 85,593 cpds / 5.1M rows")
            ext.add_leaf(f"{'✅' if state['flavorgraph_ok'] else '❌'} FlavorGraph  8,298 nodes / 147K edges")
            ext.add_leaf(f"{'✅' if state['foodon_ok'] else '❌'} FoodOn      39,682 OWL classes")
            ext.add_leaf(f"{'✅' if state['flavordb2_ok'] else '❌'} FlavorDB2   935 entities / 596 flavor descriptors")

            t1.add("🔄 全网爬取  |  food recipes / video / DB").add_leaf(
                "Agent: open-data-collector"
            )

            # ── TIER 2 ────────────────────────────────────────────────────────
            t2 = root.add("🧠 Tier 2 — Inference", expand=True)
            sy = t2.add("❌ System Y  Neo4j ❌ → L3 Agent ❌ → Baseline ❌", expand=False)
            sy.add_leaf("Neo4j: L0 import pending (PR #13)")
            sy.add_leaf("RAGAS eval: Gemini 2.0 Flash judge, Golden Set pending")

            sx = t2.add("❌ System X  聚类 ❌ → 模板 ❌ → Prototype ❌", expand=False)
            sx.add_leaf("X-axis recipe clustering by cuisine/technique")

            # ── TIER 3 ────────────────────────────────────────────────────────
            t3 = root.add("👤 Tier 3 — User Layer", expand=False)
            t3.add("❌ L6 粤菜翻译  →  ❌ Chainlit UI").add_leaf(
                "Target: 专业厨师 / 餐饮老板 / 研发团队"
            )

        # ── Memory panel ───────────────────────────────────────────────────────

        def _refresh_memory(self) -> None:
            mem_table = self.query_one("#memory-table", DataTable)
            mem_table.clear()
            now = time.time()

            for m in fetch_memory():
                if m.stale:
                    mem_table.add_row(
                        f"[yellow]{m.name}[/yellow]",
                        f"[yellow]{m.file_count}[/yellow]",
                        f"[yellow]{m.last_write_ago}[/yellow]",
                    )
                else:
                    mem_table.add_row(
                        f"[green]{m.name}[/green]",
                        str(m.file_count),
                        f"[dim]{m.last_write_ago}[/dim]",
                    )

            wiki_ago = fetch_wiki_mtime()
            mem_table.add_row("[cyan]wiki/[/cyan]", "—", f"[dim]{wiki_ago}[/dim]")

            for fname, ago in fetch_memory_files()[:4]:
                short = (fname[:18] + "…") if len(fname) > 18 else fname
                mem_table.add_row("[dim]memory[/dim]", short, f"[dim]{ago}[/dim]")

        # ── Agent panel ────────────────────────────────────────────────────────

        def _refresh_agents(self) -> None:
            agent_table = self.query_one("#agent-table", DataTable)
            agent_table.clear()

            health = self._last_health or fetch_health()
            alive_map = {a["name"]: a.get("alive", False) for a in health.agents}
            now = time.time()

            for name in AGENTS:
                restart_ts = _restarting.get(name, 0)
                if restart_ts and (now - restart_ts) < 8:
                    status = "[yellow]🔄 restarting[/yellow]"
                elif alive_map.get(name, False):
                    status = "[green]● online[/green]"
                    if restart_ts:
                        del _restarting[name]
                else:
                    status = "[red]○ offline[/red]"

                agent_table.add_row(
                    name, status, "—",
                    Button("↺", id=f"restart-{name}", variant="default"),
                )

        # ── Refresh all ────────────────────────────────────────────────────────

        def _do_full_refresh(self) -> None:
            self._check_daemon()
            self._refresh_pipeline()
            self._refresh_memory()
            self._refresh_agents()

        # ── Actions ────────────────────────────────────────────────────────────

        def action_refresh(self) -> None:
            self._do_full_refresh()

        @on(Button.Pressed, "#restart-all")
        def _restart_all(self) -> None:
            for name in AGENTS:
                _restarting[name] = time.time()
                try:
                    subprocess.run(
                        ["tmux", "send-keys", "-t", f"{TMUX_SESSION}:{name}.1", "/clear", "Enter"],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass
            self._refresh_agents()

        @on(Button.Pressed)
        def _restart_one(self, event: Button.Pressed) -> None:
            btn_id = event.button.id or ""
            if btn_id.startswith("restart-") and btn_id != "restart-all":
                name = btn_id[len("restart-"):]
                _restarting[name] = time.time()
                try:
                    subprocess.run(
                        ["tmux", "send-keys", "-t", f"{TMUX_SESSION}:{name}.1", "/clear", "Enter"],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass
                self._refresh_agents()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    if not _TEXTUAL_OK:
        _fallback_run()

    parser = argparse.ArgumentParser(description="culinary-mind Textual Dashboard")
    parser.add_argument("--agent", default="global", help="Agent name for context")
    parser.add_argument("--global", dest="is_global", action="store_true",
                        help="Show global pipeline view (default for cc-lead)")
    args = parser.parse_args()

    agent = args.agent if not args.is_global else "global"
    app = CulinaryDashboard(agent=agent)
    app.run()


if __name__ == "__main__":
    main()
