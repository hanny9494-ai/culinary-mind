# Culinary Mind v1

LLM Knowledge Curation System with Dreaming Mechanism.

Inspired by [Karpathy's LLM Knowledge Base](https://xcancel.com/karpathy/status/2039805659525644595) workflow + [Agent-Zero memory consolidation](https://deepwiki.com/frdel/agent-zero/4.3-memory-consolidation-system).

## Core Concept

```
raw/ (truth)  →  Curator (Sonnet 4.6)  →  wiki/ (compiled knowledge)
                                              ↑
                 Agents read wiki, work, produce → raw/  (cycle)
```

- **raw/** is the single source of truth. Append-only, never deleted.
- **wiki/** is compiled by LLM. Never manually edited.
- **Curator** extracts insights, detects contradictions, merges knowledge, decays stale content.
- **Dreaming**: unused knowledge gradually fades; contradictions are surfaced and resolved.

## Architecture

```
┌─────────────────────────────────────────────┐
│              raw/ (Facts Layer)              │
│  conversations  reports  dispatches  git-log │
│  decisions  results  pipeline-snapshots      │
└─────────────────────┬───────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│        Curator (Sonnet 4.6, pipeline)       │
│  EXTRACT → DETECT → DECIDE → WRITE → DECAY │
│  5 strategies: SKIP/KEEP/MERGE/REPLACE/UPDATE│
│  Runs daily 23:00 + 08:00, exits when done  │
└─────────────────────┬───────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│             wiki/ (Knowledge Layer)          │
│  STATUS.md  DECISIONS.md  ARCHITECTURE.md   │
│  CONTRADICTIONS.md  CHANGELOG.md            │
│  agents/  books/  concepts/  _archived/     │
│  Each .md has frontmatter: status, mentions, │
│  sources, related [[backlinks]]              │
└─────────────────────────────────────────────┘
```

## Quick Start

```bash
# Install
pip install requests pyyaml

# Ingest data from culinary-engine project
python3 scripts/ingest.py --source ~/culinary-engine

# Run curation (Sonnet 4.6)
python3 scripts/curate-wiki.py --full

# View wiki
ls wiki/
```

## Configuration

```yaml
# config.yaml
project_root: ~/culinary-engine
api_endpoint: http://localhost:3001/v1/chat/completions
api_key_env: L0_API_KEY
model: claude-sonnet-4-6
schedule:
  - "23:00"
  - "08:00"
decay:
  increment: 1.0        # +1 per mention per curation cycle
  decrement: 0.1        # -0.1 per cycle if not mentioned
  stale_threshold: 1.0   # below this → status: stale
  archive_threshold: 0.3 # below this → move to _archived/
```

## License

MIT
