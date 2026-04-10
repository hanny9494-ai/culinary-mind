from typing import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from dashboard.data import AgentStatus, fmt_age


class AgentRow(Horizontal):
    def __init__(self, agent: AgentStatus, restart_label: str) -> None:
        super().__init__(classes="agent-row")
        self.agent = agent
        self.restart_label = restart_label

    def compose(self) -> ComposeResult:
        yield Static(self.agent.name, classes="col-agent")
        yield Static(f"{self.agent.status_icon} {self.agent.status_text}", classes="col-status")
        yield Static(fmt_age(self.agent.last_heartbeat), classes="col-heartbeat")
        yield Static(self.agent.current_task, classes="col-task")
        yield Button(self.restart_label, id=f"restart-{self.agent.name}", classes="restart-button")


class AgentPanel(Vertical):
    def __init__(self, on_restart: Callable[[str], None], on_restart_all: Callable[[], None]) -> None:
        super().__init__(id="agent-panel")
        self._on_restart = on_restart
        self._on_restart_all = on_restart_all
        self._statuses: list[AgentStatus] = []
        self._restarting: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("Agent Status", classes="panel-title"),
            Button("Restart All", id="restart-all"),
            id="agent-toolbar",
        )
        yield Static("Agent              Status     Last Heartbeat   Current Task                          Action", id="agent-header")

    def update_statuses(self, statuses: list[AgentStatus], restarting: set[str]) -> None:
        self._statuses = statuses
        self._restarting = restarting
        for row in list(self.query(AgentRow)):
            row.remove()
        for status in statuses:
            label = "🔄" if status.name in restarting else "Restart"
            self.mount(AgentRow(status, label))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "restart-all":
            self._on_restart_all()
            return
        if event.button.id and event.button.id.startswith("restart-"):
            self._on_restart(event.button.id.removeprefix("restart-"))
