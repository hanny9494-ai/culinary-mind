from rich.text import Text
from textual.widgets import Tree

from dashboard.data import PipelineNodeData


class PipelineTree(Tree[str]):
    def __init__(self) -> None:
        super().__init__("pipeline", id="pipeline-tree")
        self.show_root = False
        self._node_refs = {}
        self._detail_refs = {}
        self._build_static_tree()

    def _build_static_tree(self) -> None:
        self.root.expand()
        tier1 = self.root.add("TIER 1 — Data Distillation", expand=True)
        tier2 = self.root.add("TIER 2 — Inference", expand=True)
        tier3 = self.root.add("TIER 3 — User Layer", expand=True)

        for key in ["l0", "l2b", "l2a", "ft", "l6", "external", "crawl"]:
            self._add_pipeline_node(tier1, key)
        self._add_pipeline_node(tier2, "system_y")
        self._add_pipeline_node(tier2, "system_x")
        self._add_pipeline_node(tier3, "user_layer")

    def _add_pipeline_node(self, parent, key: str) -> None:
        node = parent.add(f"{key}", expand=True)
        schema = node.add("schema", expand=True)
        method = node.add("method", expand=True)
        deps = node.add("deps", expand=True)
        blockers = node.add("blockers", expand=True)
        self._node_refs[key] = node
        self._detail_refs[key] = {
            "schema": schema,
            "method": method,
            "dependencies": deps,
            "blockers": blockers,
        }

    def update_pipeline(self, pipeline: dict[str, PipelineNodeData]) -> None:
        for key, data in pipeline.items():
            node = self._node_refs.get(key)
            details = self._detail_refs.get(key, {})
            if node is None:
                continue
            node.set_label(Text.from_markup(f"[{data.style}]{data.title}[/] : {data.summary}"))
            if "schema" in details:
                details["schema"].set_label(f"schema: {data.schema}")
            if "method" in details:
                details["method"].set_label(f"method: {data.method}")
            if "dependencies" in details:
                details["dependencies"].set_label(f"deps: {data.dependencies}")
            if "blockers" in details:
                details["blockers"].set_label(f"blockers: {data.blockers}")
