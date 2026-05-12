"""MF Solver Tool Registry — wrap 40 engine.solver.mf_xxx into LangGraph-style Tools.

A MFTool is a thin invocation wrapper:
    tool = get_mf_tool("MF-T03")
    out = tool.run({"A": 1e10, "Ea": 50000, "T_K": 363})

Design goals:
- No hard dependency on LangChain/LangGraph (stdlib only); but interface is
  compatible: name/description/run pattern matches @tool decorator output.
- Auto-discovery via importlib walking engine.solver.mf_*.
- Schema derived from config/solver_bounds.yaml (single source of truth).
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
BOUNDS_FILE = ROOT / "config/solver_bounds.yaml"


@dataclass
class MFTool:
    """LangChain/LangGraph-compatible tool wrapper for an MF solver."""
    mf_id: str
    canonical_name: str
    description: str
    inputs_schema: dict  # {param_name: {min, max, unit}}
    output_schema: dict  # {symbol, min, max, unit}
    _solver_module: Any = field(default=None, repr=False)

    @property
    def name(self) -> str:
        """LangChain tool name (snake_case)."""
        return f"{self.mf_id.lower().replace('-', '_')}_{self.canonical_name.lower().replace('-', '_')}"

    def run(self, params: dict) -> dict:
        """Invoke the underlying solver; returns full validity-checked output."""
        if self._solver_module is None:
            mod_name = f"engine.solver.mf_{self.mf_id.lower().replace('-', '_')}"
            self._solver_module = importlib.import_module(mod_name)
        return self._solver_module.solve(params)

    def to_langchain_tool(self):
        """Optional: return a LangChain Tool if langchain is installed.
        
        Usage:
            from langchain.tools import Tool
            ai_tool = mf_tool.to_langchain_tool()
        """
        try:
            from langchain.tools import Tool
        except ImportError:
            raise ImportError("Install langchain: pip install langchain")
        return Tool(
            name=self.name,
            description=self.description,
            func=lambda params_json: json.dumps(self.run(json.loads(params_json) if isinstance(params_json, str) else params_json)),
        )

    def get_input_summary(self) -> str:
        """Human-readable input description for LLM agent prompt."""
        lines = [f"Inputs for {self.mf_id} ({self.canonical_name}):"]
        for name, spec in self.inputs_schema.items():
            unit = spec.get("unit", "")
            lo, hi = spec.get("min"), spec.get("max")
            lines.append(f"  - {name}: {unit} (range: [{lo}, {hi}])")
        lines.append(f"Output: {self.output_schema.get('symbol', '?')} {self.output_schema.get('unit', '')}")
        return "\n".join(lines)


_TOOLS_CACHE: list[MFTool] = []


def _load_bounds() -> dict:
    if yaml is None:
        raise ImportError("PyYAML required to load solver_bounds.yaml")
    return yaml.safe_load(BOUNDS_FILE.read_text())


def _build_tool(mf_id: str, mf_spec: dict) -> MFTool:
    canonical = mf_spec.get("canonical_name", mf_id)
    inputs = mf_spec.get("inputs", [])
    inputs_schema = {i["name"]: {"min": i.get("min"), "max": i.get("max"), "unit": i.get("unit", "")} for i in inputs}
    output = mf_spec.get("output", {})
    # Try to load module to get docstring
    mod_name = f"engine.solver.{mf_id.lower().replace('-', '_')}"
    try:
        mod = importlib.import_module(mod_name)
        description = (mod.__doc__ or "").strip().split("\n")[0]
    except (ModuleNotFoundError, AttributeError):
        mod = None
        description = f"{canonical} solver"
    return MFTool(
        mf_id=mf_id,
        canonical_name=canonical,
        description=description,
        inputs_schema=inputs_schema,
        output_schema=output if isinstance(output, dict) else {},
        _solver_module=mod,
    )


def get_all_mf_tools() -> list[MFTool]:
    """Return all 40 MF tools (cached on first call)."""
    global _TOOLS_CACHE
    if _TOOLS_CACHE:
        return list(_TOOLS_CACHE)
    bounds = _load_bounds()
    solvers = bounds.get("solvers", {})
    tools = []
    for mf_id, spec in sorted(solvers.items()):
        # Skip MF-T02 parent (parent_only — children are routable)
        if mf_id == "MF-T02":
            continue
        try:
            tool = _build_tool(mf_id, spec)
            if tool._solver_module is not None:
                tools.append(tool)
        except Exception:
            pass  # silent skip if solver missing
    _TOOLS_CACHE = tools
    return list(tools)


def get_mf_tool(mf_id: str) -> MFTool:
    """Get a single MF tool by id, e.g. 'MF-T03'."""
    for t in get_all_mf_tools():
        if t.mf_id == mf_id:
            return t
    raise KeyError(f"Unknown MF id: {mf_id}")


def get_tools_by_keyword(keyword: str) -> list[MFTool]:
    """Find tools whose name/description/canonical_name contain a keyword.
    
    Useful for agent's first-pass tool selection (before invoking).
    """
    kw = keyword.lower()
    return [t for t in get_all_mf_tools()
            if kw in t.canonical_name.lower() or kw in t.description.lower() or kw in t.mf_id.lower()]
