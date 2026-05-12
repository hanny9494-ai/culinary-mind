"""Engine.agent — LangGraph-compatible Tool wrappers for 40 MF solvers.

Exports:
    get_all_mf_tools()   → list of LangChain-compatible @tool functions
    get_mf_tool(mf_id)   → single tool

Each tool wraps engine.solver.mf_xxx.solve and exposes:
- name: 'mf_t03_arrhenius' etc
- description: docstring of solve()
- input_schema: pydantic-style {param: type}
- run(params) → result dict
"""
from engine.agent.tool_registry import get_all_mf_tools, get_mf_tool, MFTool

__all__ = ["get_all_mf_tools", "get_mf_tool", "MFTool"]
