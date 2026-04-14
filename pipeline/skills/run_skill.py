#!/usr/bin/env python3
"""
pipeline/skills/run_skill.py
Unified Skill Executor — reads signals.json → calls LLM API → writes JSONL

Usage:
    python run_skill.py --skill b --book-id chuantong_yc --pages 5
    python run_skill.py --skill a --book-id van_boekel_kinetic_modeling
    python run_skill.py --skill c --book-id mc_vol3 --pages 10

Skills:
    a — ParameterSet extraction (Claude Opus 4.6 via aigocode)
    b — Recipe extraction (Gemini Flash)
    c — Ingredient atom extraction (Gemini Flash)
    d — Flavor Target + L6 Glossary (Claude Opus 4.6 via aigocode)

Output:
    output/{book_id}/skill_{a,b,c,d}/results.jsonl
    output/{book_id}/skill_{a,b,c,d}/_progress.json
"""

import os, sys, json, time, logging, argparse, re
from pathlib import Path
from typing import Any, Generator

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Config loading ────────────────────────────────────────────────────────────

def load_api_config() -> dict:
    with open(REPO_ROOT / "config" / "api.yaml") as f:
        return yaml.safe_load(f)

def resolve_env(val: Any) -> Any:
    if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
        return os.environ.get(val[2:-1], "")
    return val

# ── System prompts (from config/skill-routes.md) ──────────────────────────────

SKILL_PROMPTS: dict[str, str] = {
    "a": """\
你是食品工程参数提取器。从给定页面中提取所有可量化的科学参数。
每个参数必须绑定到 28 个 MotherFormula 之一（MF-T01~T05, MF-K01~K05, MF-M01~M06, MF-R01~R07, MF-C01~C05）。

输出纯 JSON 数组（每个参数一个对象）。如果没有可提取的参数，输出 []。

提取目标：
- 表格中的数值（温度、时间、速率常数、活化能等）
- LaTeX 公式中的系数和指数
- 图表标注中的临界值
- 参数的适用条件（基质、pH、温度范围）

输出 schema（每个元素）:
{
  "mother_formula": "Arrhenius",
  "formula_id": "MF-T03",
  "parameter_name": "Ea",
  "value": 127000,
  "unit": "J/mol",
  "conditions": {"substrate": "...", "pH": 7.0, "temperature_range": "60-90°C"},
  "source": {"book": "...", "chapter": "...", "page": ..., "table": "..."},
  "confidence": "high",
  "notes": "..."
}

如果没有参数，输出 []。不要解释。""",

    "b": """\
你是食谱提取器。从给定页面提取所有完整食谱。
如果页面不含食谱，输出 []。

输出纯 JSON 数组，每个食谱一个对象。

输出 schema:
{
  "recipe_id": "auto",
  "name": "English name",
  "name_zh": "中文名",
  "recipe_type": "main/side/sauce/dessert/bread/soup/snack",
  "ingredients": [{"name": "...", "amount": "...", "prep": "..."}],
  "steps": [{"step": 1, "text": "...", "time_min": null, "temp_c": null}],
  "equipment": [],
  "course": "main/side/sauce/dessert",
  "flavor_tags": [],
  "dietary_tags": [],
  "key_science_points": [{"l0_domain": "...", "decision_point": "...", "confidence": "high/medium/low"}],
  "source": {"book": "...", "page": ...}
}

不要解释。只输出 JSON 数组。""",

    "c": """\
你是食材参数采集器。从给定页面提取食材属性信息（品种、产地、季节、部位、营养成分、替代品）。
如果页面不含食材信息，输出 []。

输出纯 JSON 数组，每个食材一个对象。

输出 schema:
{
  "atom_id": "ingredient_name_state",
  "canonical_name": "English name",
  "canonical_name_zh": "中文名",
  "category": "meat/fish/vegetable/grain/dairy/spice/sauce/other",
  "processing_states": {
    "raw": {"moisture_pct": null, "protein_pct": null, "fat_pct": null, "pH": null, "water_activity": null},
    "cooked": {}
  },
  "varieties": [{"name": "...", "origin": "...", "note": "..."}],
  "seasons": [],
  "sensory_profile": {"texture_raw": "...", "flavor_cooked": "..."},
  "substitutes": [],
  "l0_domain_tags": [],
  "source": {"book": "...", "page": ...}
}

不要解释。只输出 JSON 数组。""",

    "d": """\
你是风味目标和粤菜术语提取器。从给定页面提取：
1. 审美词-基质-目标状态三元组 (FlavorTarget)
2. 粤菜/中式烹饪术语定义 (L6 Glossary)

如果页面不含相关内容，输出 {"flavor_targets": [], "glossary": []}。

FlavorTarget schema:
{
  "ft_id": "slug",
  "aesthetic_word": "中文词",
  "aesthetic_word_en": "English",
  "matrix_type": "基质类型",
  "substrate": "食材",
  "target_states": {"水活度等": {"target": null, "range": []}},
  "l0_domains": [],
  "source": {"book": "...", "page": ...}
}

Glossary schema:
{
  "term_zh": "术语",
  "term_en": "English",
  "definition_zh": "中文定义",
  "definition_en": "English definition",
  "l0_domains": [],
  "context": "使用场景",
  "source": {"book": "...", "page": ...}
}

不要解释。只输出包含 flavor_targets 和 glossary 两个数组的 JSON 对象。""",
}

SKILL_MODELS = {
    "a": "aigocode",
    "b": "gemini_flash",
    "c": "gemini_flash",
    "d": "aigocode",
}

SKILL_SIGNAL_KEY = {"a": "A", "b": "B", "c": "C", "d": "D"}

# ── LLM API callers ───────────────────────────────────────────────────────────

def call_aigocode(
    system: str,
    user: str,
    cfg: dict,
    retries: int = 3,
    log: logging.Logger | None = None,
) -> str:
    """Call aigocode API with SSE streaming (non-streaming drops content)."""
    l = log or logging.getLogger(__name__)
    endpoint = resolve_env(cfg["endpoint"])
    api_key  = resolve_env(cfg["api_key"])
    model    = cfg["models"]["opus"]

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 4096,
        "stream": True,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    for attempt in range(1, retries + 1):
        try:
            chunks: list[str] = []
            with httpx.Client(trust_env=False, timeout=cfg.get("timeout_sec", 120), follow_redirects=False) as client:
                with client.stream("POST", endpoint, headers=headers, json=body) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            ev = json.loads(data_str)
                            if ev.get("type") == "content_block_delta":
                                delta = ev.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    chunks.append(delta["text"])
                        except Exception:
                            pass
            return "".join(chunks).strip()
        except Exception as e:
            l.warning(f"[skill] aigocode attempt {attempt} failed: {e}")
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
    return ""

def call_gemini_flash(
    system: str,
    user: str,
    cfg: dict,
    retries: int = 3,
    log: logging.Logger | None = None,
) -> str:
    """Call Gemini Flash via Google REST API."""
    l = log or logging.getLogger(__name__)
    base     = resolve_env(cfg["endpoint"])
    api_key  = resolve_env(cfg["api_key"])
    model    = cfg["models"]["flash"]
    url      = f"{base}/models/{model}:generateContent?key={api_key}"

    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": 8192, "temperature": 0},
    }

    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(trust_env=False, timeout=cfg.get("timeout_sec", 60), follow_redirects=False) as client:
                resp = client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            # Parse Gemini response
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError(f"Empty candidates in Gemini response: {data}")
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            return "".join(p.get("text","") for p in parts).strip()
        except Exception as e:
            l.warning(f"[skill] gemini_flash attempt {attempt} failed: {e}")
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
    return ""

def call_llm(skill: str, user_text: str, cfg: dict, log: logging.Logger) -> str:
    system = SKILL_PROMPTS[skill]
    provider = SKILL_MODELS[skill]
    if provider == "aigocode":
        return call_aigocode(system, user_text, cfg["aigocode"], log=log)
    else:
        return call_gemini_flash(system, user_text, cfg["gemini_flash"], log=log)

# ── JSON extraction ───────────────────────────────────────────────────────────

def extract_json(text: str) -> Any:
    """Extract JSON from LLM response (strips markdown fences, thinking blocks)."""
    # Remove <think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Extract fenced block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    # Extract first array or object
    m2 = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
    if m2:
        try:
            return json.loads(m2.group(1))
        except Exception:
            pass
    return None

# ── Progress tracking ─────────────────────────────────────────────────────────

def load_progress(out_dir: Path) -> set[int]:
    """Return set of already-processed page numbers."""
    progress_path = out_dir / "_progress.json"
    if not progress_path.exists():
        return set()
    try:
        data = json.loads(progress_path.read_text())
        return set(data.get("done_pages", []))
    except Exception:
        return set()

def save_progress(out_dir: Path, done_pages: set[int], total: int, failed: int) -> None:
    p = {
        "done": len(done_pages),
        "total": total,
        "failed": failed,
        "done_pages": sorted(done_pages),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out_dir / "_progress.json").write_text(json.dumps(p, indent=2))

# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Skill Executor — extract structured data from book pages")
    p.add_argument("--skill",    required=True, choices=["a","b","c","d"], help="Skill to run")
    p.add_argument("--book-id",  help="Book ID → reads output/{book_id}/signals.json + pages.json")
    p.add_argument("--signals",  help="Explicit signals.json path")
    p.add_argument("--pages-file", help="Explicit pages.json path (default: same dir as signals)")
    p.add_argument("--pages",    type=int, default=None, help="Max pages to process")
    p.add_argument("--resume",   action="store_true", default=True, help="Skip already-processed pages")
    p.add_argument("--no-resume", dest="resume", action="store_false")
    p.add_argument("--force",    action="store_true")
    p.add_argument("--concurrency", type=int, default=1, help="Parallel pages (default: 1; use carefully)")
    p.add_argument("--pilot",    action="store_true", help="Print each result to stdout")
    return p.parse_args()

def main() -> None:
    args = parse_args()
    skill = args.skill
    cfg = load_api_config()

    # Resolve paths
    if args.book_id:
        book_id = args.book_id
        signals_path  = REPO_ROOT / "output" / book_id / "signals.json"
        pages_path    = REPO_ROOT / "output" / book_id / "pages.json"
        out_dir       = REPO_ROOT / "output" / book_id / f"skill_{skill}"
    elif args.signals:
        signals_path = Path(args.signals)
        pages_path   = Path(args.pages_file) if args.pages_file else signals_path.parent / "pages.json"
        book_id      = signals_path.parent.name
        out_dir      = signals_path.parent / f"skill_{skill}"
    else:
        print("ERROR: Provide --book-id or --signals", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(out_dir / "_run.log"),
            logging.StreamHandler(),
        ],
    )
    log = logging.getLogger(f"skill_{skill}")
    log.info(f"book_id={book_id}, skill={skill}, provider={SKILL_MODELS[skill]}")

    # Load data
    if not signals_path.exists():
        log.error(f"signals.json not found: {signals_path}. Run signal_router.py first.")
        sys.exit(1)
    if not pages_path.exists():
        log.error(f"pages.json not found: {pages_path}. Run ocr_claw.py first.")
        sys.exit(1)

    signals_list: list[dict] = json.loads(signals_path.read_text())
    pages_list:   list[dict] = json.loads(pages_path.read_text())
    pages_map = {p["page"]: p["text"] for p in pages_list}

    signal_key = SKILL_SIGNAL_KEY[skill]

    # Filter pages where skill signal is true
    target_pages = [
        s for s in signals_list
        if s.get("signals", {}).get(signal_key, False) and not s.get("skip_reason")
    ]

    if args.pages:
        target_pages = target_pages[:args.pages]

    log.info(f"Target pages for skill {skill}: {len(target_pages)}/{len(signals_list)}")

    # Resume
    done_pages = load_progress(out_dir) if (args.resume and not args.force) else set()
    todo = [p for p in target_pages if p["page"] not in done_pages]
    log.info(f"Processing {len(todo)}/{len(target_pages)} pages (skipping {len(target_pages)-len(todo)})")

    # Open results file (append mode for resume)
    results_file = open(results_path, "a" if (args.resume and not args.force) else "w")
    failed = 0
    total = len(target_pages)

    t0 = time.time()
    for i, sig in enumerate(todo):
        page_num = sig["page"]
        page_text = pages_map.get(page_num, "")

        if not page_text.strip():
            log.info(f"  page {page_num}: empty, skipping")
            done_pages.add(page_num)
            continue

        # Build user message with hints
        hints = sig.get("hints", {})
        skill_hints = hints.get(signal_key, {})
        hint_str = ""
        if skill == "a" and skill_hints.get("mf_candidates"):
            hint_str = f"\n[Hint: possible MF matches: {', '.join(skill_hints['mf_candidates'])}]"
        elif skill == "c" and skill_hints.get("ingredients_detected"):
            hint_str = f"\n[Hint: detected ingredients: {', '.join(skill_hints['ingredients_detected'])}]"

        user_msg = f"Book: {book_id}\nPage: {page_num}{hint_str}\n\n{page_text[:4000]}"

        try:
            raw_response = call_llm(skill, user_msg, cfg, log)
            parsed = extract_json(raw_response)

            if parsed is None:
                log.warning(f"  page {page_num}: could not parse JSON")
                record = {"_page": page_num, "_skill": skill, "_error": "parse_failed", "_raw": raw_response[:200]}
                failed += 1
            else:
                # Normalize: skill a/b/c expect array, d expects object
                if skill in ("a","b","c"):
                    items = parsed if isinstance(parsed, list) else []
                else:  # d
                    items_d = [
                        {**ft, "_type": "flavor_target"} for ft in (parsed.get("flavor_targets") or [])
                    ] + [
                        {**gl, "_type": "glossary"} for gl in (parsed.get("glossary") or [])
                    ]
                    items = items_d

                if items:
                    for item in items:
                        item["_page"] = page_num
                        item["_skill"] = skill
                        item["_book"] = book_id
                        results_file.write(json.dumps(item, ensure_ascii=False) + "\n")
                    log.info(f"  page {page_num}: {len(items)} records")
                else:
                    log.info(f"  page {page_num}: no records (empty result)")
                    record = None

                if args.pilot and items:
                    print(f"\n  ── Page {page_num} Skill {skill.upper()} ──")
                    for item in items[:2]:
                        print(f"  {json.dumps(item, ensure_ascii=False)[:200]}")

        except Exception as e:
            log.error(f"  page {page_num}: API error: {e}")
            failed += 1
            results_file.write(json.dumps({"_page": page_num, "_skill": skill, "_error": str(e), "_book": book_id}, ensure_ascii=False) + "\n")

        done_pages.add(page_num)

        # Checkpoint every 10 pages
        if (i + 1) % 10 == 0:
            results_file.flush()
            save_progress(out_dir, done_pages, total, failed)
            elapsed = time.time() - t0
            log.info(f"Checkpoint: {i+1}/{len(todo)}, failed={failed}, {elapsed:.0f}s")

    results_file.close()
    save_progress(out_dir, done_pages, total, failed)

    elapsed = time.time() - t0
    done_count = len(done_pages)
    print(f"\n── Skill {skill.upper()} Summary ──")
    print(f"  book_id:  {book_id}")
    print(f"  processed:{done_count}")
    print(f"  failed:   {failed}")
    print(f"  time:     {elapsed:.1f}s")
    print(f"  output:   {results_path}")

if __name__ == "__main__":
    main()
