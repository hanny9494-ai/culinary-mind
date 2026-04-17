from rich.text import Text
from textual.widgets import Static

from dashboard.data import AgentMemoryStatus, MemoryFileInfo, fmt_age


class MemoryPanel(Static):
    def render_memory(
        self,
        agent_memory: list[AgentMemoryStatus],
        wiki_modified_ts: float | None,
        memory_files: list[MemoryFileInfo],
    ) -> None:
        text = Text()
        text.append("Memory / Recency\n", style="bold")
        for item in agent_memory:
            style = "yellow" if item.stale else "green"
            text.append(f"{item.name:<18}", style=style)
            text.append(f" {item.file_count:>2} files ", style="white")
            text.append(fmt_age(item.last_output_ts), style=style)
            text.append("\n")
        text.append("\nwiki/ ", style="bold")
        text.append(fmt_age(wiki_modified_ts), style="yellow" if not wiki_modified_ts else "green")
        text.append("\n\n.ce-hub/memory\n", style="bold")
        if not memory_files:
            text.append("?\n", style="white")
        for file_info in memory_files:
            text.append(f"{file_info.path}\n", style="cyan")
            text.append(f"  {fmt_age(file_info.modified_ts)}\n", style="white")
        self.update(text)
