"""
agent_panel.py — Agent status table + restart buttons.
"""

import subprocess
import time
from textual.app import ComposeResult
from textual.widgets import Static, Button, DataTable
from textual.containers import Horizontal, Vertical
from textual import on


# Agents restarting: {name: restart_ts}
_restarting: dict[str, float] = {}

TMUX_SESSION = "cehub"


def _restart_agent(name: str) -> None:
    """Send /clear to the agent's tmux pane (pane 1 = agent pane)."""
    _restarting[name] = time.time()
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{TMUX_SESSION}:{name}.1", "/clear", "Enter"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


class AgentPanel(Vertical):
    """Bottom panel: agent status list + restart buttons."""

    DEFAULT_CSS = """
    AgentPanel {
        height: auto;
        max-height: 20;
        border: solid $accent;
        padding: 0 1;
    }
    AgentPanel Button {
        min-width: 9;
        height: 1;
        margin: 0;
    }
    AgentPanel DataTable {
        height: auto;
    }
    AgentPanel #restart-all-row {
        height: 3;
        align: right middle;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="restart-all-row"):
            yield Static("🤖 Agent Status", classes="panel-title")
            yield Button("↺ Restart All", id="restart-all", variant="warning")
        yield DataTable(id="agent-table", show_cursor=False)

    def on_mount(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.add_columns("Agent", "Status", "Last Heartbeat", "Task", "")
        self._refresh_data()
        self.set_interval(10, self._refresh_data)

    def _refresh_data(self) -> None:
        from ..data import fetch_agents, fetch_health

        health = fetch_health()
        agents = fetch_agents(health)
        table = self.query_one("#agent-table", DataTable)
        table.clear()

        now = time.time()
        for a in agents:
            name = a.name
            # Check if restarting
            restart_ts = _restarting.get(name, 0)
            if restart_ts > 0 and (now - restart_ts) < 8:
                status = "[yellow]🔄 restarting[/yellow]"
            elif a.alive:
                status = "[green]● online[/green]"
                if restart_ts > 0:
                    del _restarting[name]
            else:
                status = "[red]○ offline[/red]"

            hb = a.last_heartbeat_ago
            task = (a.current_task[:20] + "…") if len(a.current_task) > 20 else a.current_task

            table.add_row(name, status, hb, task,
                          Button("↺", id=f"restart-{name}", variant="default"))

    @on(Button.Pressed, "#restart-all")
    def _restart_all(self) -> None:
        from ..data import AGENTS
        for name in AGENTS:
            _restart_agent(name)
        self._refresh_data()

    @on(Button.Pressed)
    def _restart_one(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("restart-") and btn_id != "restart-all":
            name = btn_id[len("restart-"):]
            _restart_agent(name)
            self._refresh_data()
