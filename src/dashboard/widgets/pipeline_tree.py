"""
pipeline_tree.py — Textual widget: collapsible 3-tier project pipeline tree.
"""

from textual.app import ComposeResult
from textual.widgets import Static, Tree
from textual.widgets._tree import TreeNode
from textual import on
from ..data import fetch_pipeline_state as get_pipeline_state   # lazy import to avoid circular


STATUS_ICONS = {
    "ok":       "✅",
    "error":    "❌",
    "progress": "🔄",
    "pending":  "⬜",
    "warn":     "⚠️",
}


def _icon(status: str) -> str:
    return STATUS_ICONS.get(status, "?")


def _s(ok: bool, progress: bool = False) -> str:
    if progress:
        return "progress"
    return "ok" if ok else "error"


class PipelineTree(Static):
    """Three-tier pipeline tree with expandable nodes."""

    DEFAULT_CSS = """
    PipelineTree {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        tree: Tree = Tree("🍳 culinary-mind — Project Pipeline", id="pipeline-tree")
        tree.root.expand()
        yield tree

    def on_mount(self) -> None:
        self._populate()
        self.set_interval(10, self._refresh_tree)

    def _populate(self) -> None:
        tree = self.query_one("#pipeline-tree", Tree)
        tree.clear()
        state = get_pipeline_state()
        self._build_tree(tree.root, state)
        tree.root.expand()

    def _refresh_tree(self) -> None:
        self._populate()

    def _build_tree(self, root: TreeNode, state: dict) -> None:
        # ── TIER 1: Data Distillation ──────────────────────────────────────────
        t1 = root.add("📦 Tier 1 — Data Distillation", expand=True)

        # L0
        l0_icon = _icon(_s(state["l0_ok"]))
        neo_icon = _icon(_s(state["neo4j_ok"], progress=state["neo4j_count"] > 0 and not state["neo4j_ok"]))
        l0_node = t1.add(
            f"{l0_icon} L0 科学原理 ({state['l0_count']:,} 条)  |  Neo4j: {neo_icon} {state['neo4j_count']:,} 条",
            expand=False,
        )
        l0_node.add_leaf("Domain: 17 domains (protein_science, thermal_dynamics, fermentation …)")
        l0_node.add_leaf("Method: Stage4 9b annotation + Stage2/3 targeted domain fill")
        l0_node.add_leaf("Dependency: DashScope qwen3.5:9b / 2b (local Ollama)")
        l0_node.add_leaf("Blocker: Neo4j re-import needed with Gemini 3072-dim embeddings (PR #13)")

        # L2b
        l2b_icon = _icon(_s(state["l2b_ok"]))
        l2b_node = t1.add(
            f"{l2b_icon} L2b 食谱校准库 ({state['l2b_count']:,} 条)  |  Step B: ❌ 0/{state['l2b_count']:,}",
            expand=False,
        )
        l2b_node.add_leaf("Step A: Recipe extraction from 63 books (DONE)")
        l2b_node.add_leaf("Step B: L0 domain tagging + parameter binding (PENDING)")
        l2b_node.add_leaf("Schema: recipe-normalized-v1.json (docs/schemas/)")

        # L2a
        l2a_status = "progress" if state["l2a_count"] > 0 else "error"
        l2a_icon = _icon(l2a_status)
        l2a_node = t1.add(
            f"{l2a_icon} L2a 食材原子库 ({state['l2a_count']:,} 条)  |  R2 蒸馏: {'🔄 running' if state['l2a_count'] > 0 else '❌ not started'}",
            expand=False,
        )
        l2a_node.add_leaf("Source: distill_r2.py → Lingya gemini-3-flash-preview-search")
        l2a_node.add_leaf("Target: 52,273 L0 nodes → ingredient parameters")
        l2a_node.add_leaf("Dependency: L0 complete ✅")

        # FT
        t1.add(f"❌ FT 风味目标库 (0 条)  |  依赖 Pass 1 (未设计)").add_leaf(
            "Source plan: FlavorDB2 (596 descriptors) + Pass1 multi-task extraction"
        )

        # L6
        t1.add(f"❌ L6 翻译层 (0 条)  |  依赖 Pass 1").add_leaf(
            "Scope: Cantonese aesthetic vocabulary ↔ system language mapping"
        )

        # External data
        ext_node = t1.add("🗄️  外部数据源", expand=True)
        ext_node.add_leaf(f"{'✅' if state['foodb_ok'] else '❌'} FooDB      — 1,342 foods / 85,593 cpds / 5.1M content rows (mg/100g)")
        ext_node.add_leaf(f"{'✅' if state['flavorgraph_ok'] else '❌'} FlavorGraph — 8,298 nodes / 147,179 edges / 1,645 aroma cpds")
        ext_node.add_leaf(f"{'✅' if state['foodon_ok'] else '❌'} FoodOn     — 39,682 OWL classes / processing ontology")
        ext_node.add_leaf(f"{'✅' if state['flavordb2_ok'] else '❌'} FlavorDB2  — 935 entities / 25,595 molecules / 596 flavor descriptors")

        # Web crawl
        t1.add("🔄 全网爬取  |  食谱 X 条 | 视频 X/36 | DB X/X").add_leaf(
            "Agent: open-data-collector (OpenClaw, Mac Mini sandbox)"
        )

        # ── TIER 2: Inference ──────────────────────────────────────────────────
        t2 = root.add("🧠 Tier 2 — Inference Systems", expand=True)

        sy_node = t2.add("❌ System Y  |  Neo4j ❌ → L3 Agent ❌ → Baseline ❌", expand=False)
        sy_node.add_leaf("Neo4j: L0 graph import (PR #13 pending merge)")
        sy_node.add_leaf("L3 Agent: LangGraph + Graphiti (not started)")
        sy_node.add_leaf("Baseline: RAGAS 4-metric eval (run_ragas.py ready, Golden Set pending)")
        sy_node.add_leaf("Judge: Gemini 2.0 Flash (independent, avoids Claude self-bias)")

        sx_node = t2.add("❌ System X  |  聚类 ❌ → 模板 ❌ → Prototype ❌", expand=False)
        sx_node.add_leaf("X-axis: recipe clustering by cuisine/technique")
        sx_node.add_leaf("Template induction: pending L2b Step B + L2a completion")
        sx_node.add_leaf("Prototype: Jeff calibration sprint (future)")

        # ── TIER 3: User Layer ─────────────────────────────────────────────────
        t3 = root.add("👤 Tier 3 — User Layer", expand=True)
        t3.add("❌ L6 粤菜翻译  →  ❌ Chainlit UI").add_leaf(
            "Target users: 专业厨师 / 餐饮老板 / 研发团队"
        )
