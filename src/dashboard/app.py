import os
for _proxy_key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_proxy_key, None)

import argparse
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Static
except ModuleNotFoundError:
    print("Textual is not installed. Run: pip install textual")
    raise SystemExit(1)

from dashboard.data import DashboardDataSource, DashboardSnapshot, fmt_uptime
from dashboard.widgets.agent_panel import AgentPanel
from dashboard.widgets.memory_panel import MemoryPanel
from dashboard.widgets.pipeline_tree import PipelineTree


class DashboardApp(App):
    CSS = """
    Screen {
        layout: vertical;
        overflow: hidden;
        background: #101414;
        color: #f3efe3;
    }

    #header {
        height: 1;
        padding: 0 1;
        background: #1a2d2a;
        color: #f3efe3;
    }

    #body {
        height: 1fr;
        layout: vertical;
        overflow: hidden;
    }

    #top {
        height: 1fr;
        layout: horizontal;
        overflow: hidden;
    }

    #pipeline-panel {
        width: 2fr;
        border: round #36534f;
        padding: 0 1;
        overflow: hidden;
    }

    #memory-panel {
        width: 1fr;
        border: round #7b6d46;
        padding: 0 1;
        overflow: hidden;
    }

    #agent-panel {
        height: 11;
        border: round #5f4a36;
        padding: 0 1;
        overflow: hidden;
    }

    #pipeline-tree {
        height: 100%;
    }

    #agent-toolbar {
        height: 1;
        layout: horizontal;
    }

    .panel-title {
        width: 1fr;
        text-style: bold;
    }

    #agent-header {
        height: 1;
        color: #d8d4c8;
    }

    .agent-row {
        height: 1;
        layout: horizontal;
    }

    .col-agent {
        width: 18;
    }

    .col-status {
        width: 11;
    }

    .col-heartbeat {
        width: 16;
    }

    .col-task {
        width: 1fr;
    }

    .restart-button {
        width: 10;
        min-width: 10;
    }
    """

    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    def __init__(self, agent: str | None = None, global_view: bool = False) -> None:
        super().__init__()
        self.agent = agent
        self.global_view = global_view
        self.data_source = DashboardDataSource()
        self.snapshot: DashboardSnapshot | None = None
        self.restart_state: dict[str, float] = {}
        self.daemon_failures = 0
        self.header_restart_note = ""

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with Vertical(id="body"):
            with Horizontal(id="top"):
                with Vertical(id="pipeline-panel"):
                    yield Static("Pipeline", classes="panel-title")
                    yield PipelineTree()
                yield MemoryPanel(id="memory-panel")
            yield AgentPanel(self.restart_agent, self.restart_all_agents)

    def on_mount(self) -> None:
        self.refresh_dashboard()
        self.set_interval(10, self.refresh_dashboard)
        self.set_interval(60, self.watchdog_tick)

    def action_refresh(self) -> None:
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        snapshot = self.data_source.collect_snapshot()
        self.snapshot = snapshot
        self.pipeline_tree.update_pipeline(snapshot.pipeline)
        self.memory_panel.render_memory(snapshot.agent_memory, snapshot.wiki_modified_ts, snapshot.memory_files)
        self._prune_restart_state()
        self.agent_panel.update_statuses(snapshot.agent_statuses, set(self.restart_state))
        self._update_header(snapshot)
        if snapshot.daemon_up:
            self.daemon_failures = 0

    def watchdog_tick(self) -> None:
        snapshot = self.data_source.collect_snapshot()
        self.snapshot = snapshot
        if snapshot.daemon_up:
            self.daemon_failures = 0
            self.header_restart_note = ""
            self._update_header(snapshot)
            return
        self.daemon_failures += 1
        if self.daemon_failures >= 3:
            ok, error = self.data_source.restart_daemon()
            self.header_restart_note = f" restart #{self.data_source.restart_attempts}" if ok else f" restart failed: {error}"
            self.daemon_failures = 0
        self._update_header(snapshot)

    def restart_agent(self, agent_name: str) -> None:
        ok, error = self.data_source.send_restart_clear(agent_name)
        if ok:
            self.restart_state[agent_name] = time.time() + 5
            self.notify(f"sent /clear to {agent_name}", timeout=2)
        else:
            self.notify(f"restart failed for {agent_name}: {error}", severity="error", timeout=4)
        self.refresh_dashboard()

    def restart_all_agents(self) -> None:
        for agent_name in [status.name for status in (self.snapshot.agent_statuses if self.snapshot else [])]:
            ok, _ = self.data_source.send_restart_clear(agent_name)
            if ok:
                self.restart_state[agent_name] = time.time() + 5
        self.refresh_dashboard()

    def _prune_restart_state(self) -> None:
        now = time.time()
        stale = [name for name, until in self.restart_state.items() if until <= now]
        for name in stale:
            self.restart_state.pop(name, None)

    def _update_header(self, snapshot: DashboardSnapshot) -> None:
        scope = "global" if self.global_view else (self.agent or "local")
        dot = "[green]●[/green]" if snapshot.daemon_up else "[red]●[/red]"
        status = "daemon up" if snapshot.daemon_up else "[red]DAEMON DOWN[/red]"
        uptime = fmt_uptime(snapshot.daemon_uptime_seconds)
        restart_bits = f" | attempts {snapshot.daemon_restart_attempts}"
        if self.header_restart_note:
            restart_bits += self.header_restart_note
        self.header.update(
            Text.from_markup(
                f"[b]culinary-mind dashboard[/b] | {dot} {status} | uptime {uptime} | scope {scope}{restart_bits}"
            )
        )

    @property
    def header(self) -> Static:
        return self.query_one("#header", Static)

    @property
    def pipeline_tree(self) -> PipelineTree:
        return self.query_one(PipelineTree)

    @property
    def memory_panel(self) -> MemoryPanel:
        return self.query_one(MemoryPanel)

    @property
    def agent_panel(self) -> AgentPanel:
        return self.query_one(AgentPanel)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="culinary-mind Textual dashboard")
    parser.add_argument("--agent", default=None)
    parser.add_argument("--global", action="store_true", dest="global_view")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    DashboardApp(agent=args.agent, global_view=args.global_view).run()


if __name__ == "__main__":
    main()
