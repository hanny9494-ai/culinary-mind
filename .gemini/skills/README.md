# Antigravity Skills — Usage Guide

## What is a Skill?
A Skill is a context file injected into Gemini Pro conversations to give it project-specific knowledge.
The `culinary-architect` skill enables Gemini to act as a co-architect with full project context.

## Files

| File | Purpose |
|---|---|
| `culinary-architect.md` | Main skill — 七层架构 + 17域 + 28公式 + Neo4j Schema + ParameterSet JSON格式 |

Mirrored at: `~/.gemini/antigravity/culinary-architect.md`
Also accessible via MCP filesystem at: `~/culinary-mind/.gemini/skills/culinary-architect.md`

## How to Use in Antigravity

### Option A: Attach via MCP filesystem
In an Antigravity conversation, reference the skill via MCP:
```
@filesystem read ~/culinary-mind/.gemini/skills/culinary-architect.md
```
Then say: "Use this as your context for all subsequent responses."

### Option B: Paste directly
Open the file and paste the full content at the start of a new Antigravity conversation.

### Option C: Workflow Integration (once /distill workflow is ready)
The `/distill` workflow will automatically load this skill.

## What the Skill Injects

1. **Project identity** — what the engine does, who it's for
2. **七层架构 (L0-L6+FT)** — full layer definitions and status
3. **17 domains** — complete list for L0 classification
4. **28 Mother Formulas** — complete registry with SymPy expressions, units, source books
5. **Neo4j Schema** — all 6 node types + key relationships
6. **Track A ParameterSet JSON format** — exact output schema for parameter extraction
7. **Quality standards** — SymPy parseability, unit rules, anti-hallucination rules
8. **Technical constraints** — API endpoints, concurrency limits, proxy settings
9. **Architecture review protocol** (D8) — how Gemini should respond to architecture proposals

## When to Use This Skill

- Reviewing architecture proposals from the architect agent
- Extracting quantitative parameters from food science textbooks
- Validating Neo4j schema changes
- Classifying new formulas into the 28-formula registry
- Cross-checking L0 scientific principles

## Keeping the Skill Updated

This file is maintained by the coder agent. When updating:
1. Edit `culinary-architect.md`
2. Run `cp .gemini/skills/culinary-architect.md ~/.gemini/antigravity/culinary-architect.md`
3. Commit to feat/* branch
