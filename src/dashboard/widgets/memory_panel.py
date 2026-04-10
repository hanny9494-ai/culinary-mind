"""
memory_panel.py — Agent memory / output recency panel.
Shows last write time per agent raw/ dir; highlights stale > 24h.
"""

from textual.app import ComposeResult
from textual.widgets import Static, DataTable
from textual.reactive import reactive


class MemoryPanel(Static):
    """Right sidebar: agent output recency + wiki + memory files."""

    DEFAULT_CSS = """
    MemoryPanel {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    MemoryPanel DataTable {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("📝 Memory & Output Recency", classes="panel-title")
        yield DataTable(id="memory-table", show_cursor=False)

    def on_mount(self) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.add_columns("Agent", "Files", "Last Write")
        self._refresh_data()
        self.set_interval(30, self._refresh_data)

    def _refresh_data(self) -> None:
        from ..data import fetch_memory, fetch_wiki_mtime, fetch_memory_files

        table = self.query_one("#memory-table", DataTable)
        table.clear()

        memories = fetch_memory()
        for m in memories:
            name = m.name
            count = str(m.file_count) if m.file_count > 0 else "0"
            ago = m.last_write_ago
            # Yellow styling for stale agents
            if m.stale:
                row = (f"[yellow]{name}[/yellow]",
                       f"[yellow]{count}[/yellow]",
                       f"[yellow]{ago}[/yellow]")
            else:
                row = (f"[green]{name}[/green]", count, f"[dim]{ago}[/dim]")
            table.add_row(*row)

        # Wiki row
        wiki_ago = fetch_wiki_mtime()
        table.add_row("[cyan]wiki/[/cyan]", "—", f"[dim]{wiki_ago}[/dim]")

        # Memory files section
        mem_files = fetch_memory_files()
        if mem_files:
            self.query_one("#memory-table").add_row("", "", "")
            for fname, ago in mem_files[:5]:
                short = fname[:20] + "…" if len(fname) > 20 else fname
                table.add_row(f"[dim].ce-hub/memory[/dim]", short, f"[dim]{ago}[/dim]")
