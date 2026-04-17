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
    """Replace ${VAR} placeholders anywhere in a string."""
    if not isinstance(val, str):
        return val
    return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), val)

# ── System prompts (from config/skill-routes.md) ──────────────────────────────

SKILL_PROMPTS: dict[str, str] = {
    "a": """你是食品工程参数提取器（Skill A 专用）。从给定页面提取可绑定到物理/化学方程的定量参数。

【提取标准 — Scale-up Test】
只提取满足以下条件的数值：放大食材体积/改变温度/改变时间后，这个数字还能用于预测新结果。
  能预测 → 提取（物质固有属性/动力学常数/经验方程系数）
  不能（实验终点/食谱操作参数）→ 跳过，输出 []

提取目标：
- 动力学常数/相变阈值：活化能(Ea)、变性温度、凝胶化温度、Tg、D-value、z-value
- 热物性/传递参数：热导率(k)、比热容(Cp)、密度(ρ)、扩散系数(D_eff)
- 经验方程系数：流变模型参数(τ₀, n, β)、HLB 值、水活度阈值
- 系统性数据表中的参数（整列数值代表物质属性，非单次实验结果）

不提取（→ 返回 []）：
- 食谱操作参数："160°C 炸 3 分钟"（这是 Skill B）
- 实验终点 End-state："水浴 1h 汁液流失 15%"
- 设备依赖数据："微波 800W 2min 土豆中心 85°C"

每个参数绑定到 28 个 MotherFormula 之一：
MF-T01~T05（热动力学）, MF-K01~K05（动力学）, MF-M01~M06（质量传递）,
MF-R01~R07（流变/结构）, MF-C01~C05（化学反应）

输出纯 JSON 数组。如果没有可提取的参数，输出 []。

输出 schema（每个元素）：
{
  "mother_formula": "Arrhenius",
  "formula_id": "MF-T03",
  "parameter_name": "卵清蛋白变性温度",
  "value": 80,
  "unit": "°C",
  "conditions": {"substrate": "蛋清", "pH": 7.0, "temperature_range": "75-85°C"},
  "source": {"book": "...", "chapter": "...", "page": ..., "table": "..."},
  "confidence": "high",
  "causal_context": "80°C以上卵清蛋白发生二硫键交联，凝胶网络收缩挤出水分",
  "notes": "..."
}

causal_context 规则：
- 1-2 句描述该参数驱动的物理/化学机制
- 从同一页上下文提取，不要编造；没有因果描述则留空 ""
- 用于链接到 L0 因果链（Neo4j PARAMETER -[:DRIVES]-> MECHANISM）

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

    "d": "__SKILL_D_DYNAMIC__",  # resolved at runtime based on book language
}

# ── Skill D language-specific prompts ────────────────────────────────────────
# Shared schema preamble — embedded in both zh and en variants
_SKILL_D_SCHEMA = """
FlavorTarget schema:
{
  "ft_id": "slug",
  "aesthetic_word": "审美词/sensory word",
  "aesthetic_word_en": "English",
  "matrix_type": "基质类型/matrix type",
  "substrate": "食材/ingredient",
  "target_states": {"parameter": {"target": null, "range": []}},
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
  "context": "使用场景/usage context",
  "source": {"book": "...", "page": ...}
}
"""

SKILL_D_PROMPTS: dict[str, str] = {
    "zh": """\
你是粤菜审美词和中式烹饪术语提取器。从给定页面提取：
1. 审美词-基质-目标状态三元组 (FlavorTarget)
   - 重点关注：镬气、嫩滑、爽脆、入口即化、断生、过冷河、飞水、走油等粤菜特有审美表达
   - 每个审美词必须绑定具体食材/基质
   - target_states 映射到可量化物理参数
2. 粤菜/中式烹饪术语定义 (L6 Glossary)
   - 术语的上下文实体（在什么食材/场景下使用）
   - 映射到 L0 物理现象

如果页面不含相关内容，输出 {"flavor_targets": [], "glossary": []}

不要解释。只输出包含 flavor_targets 和 glossary 两个数组的 JSON 对象。""",

    "en": """\
You are a sensory descriptor and flavor terminology extractor. From the given page, extract:
1. FlavorTarget triplets: aesthetic_word x substrate x target_states
   - Focus on: texture descriptors (crispy, tender, silky, creamy, crunchy, chewy, flaky),
     mouthfeel terms (succulent, velvety, unctuous), flavor profile terms (umami, bright, round)
   - Each aesthetic word must be bound to a specific ingredient/matrix
   - target_states map to quantifiable physical parameters
2. Culinary glossary entries
   - Context entity (which ingredient/scenario)
   - Mapped phenomenon (physical process)

If page has no relevant content, output {"flavor_targets": [], "glossary": []}

Output only the JSON object with flavor_targets and glossary arrays. No explanations.""",
}


SKILL_MODELS = {
    "a": "lingya_opus",    # switched from aigocode (余额耗尽 2026-04-17)
    "b": "gemini_flash",
    "c": "gemini_flash",
    "d": "lingya_opus",    # switched from aigocode
}

SKILL_SIGNAL_KEY = {"a": "A", "b": "B", "c": "C", "d": "D"}

# ── LLM API callers ───────────────────────────────────────────────────────────

# Backoff delays for retry: 2s / 4s / 8s on 429/503
_RETRY_DELAYS = [2, 4, 8]
_RETRY_STATUS = {429, 500, 502, 503, 504}
_FATAL_STATUS  = {401, 403}          # auth errors — never retry


def _should_retry(exc: Exception) -> bool:
    """Return True if this exception warrants a retry with backoff."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRY_STATUS
    return isinstance(exc, (httpx.RequestError, httpx.TimeoutException))


def _is_fatal_status(exc: Exception) -> bool:
    """Return True for auth errors that must never be retried (401/403)."""
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in _FATAL_STATUS
    )


def call_anthropic_stream(
    system: str,
    user: str,
    endpoint: str,
    api_key: str,
    model: str,
    timeout_sec: float = 120,
    retries: int = 3,
    log: logging.Logger | None = None,
    label: str = "llm",
) -> str:
    """
    Generic Anthropic-format SSE streaming call.
    Works for aigocode AND 灵雅 (L0_API_ENDPOINT) — both use /v1/messages.
    Non-streaming mode is known to drop message.content on some servers,
    so we always use stream=True and accumulate text_delta events.
    """
    l = log or logging.getLogger(__name__)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 8192,
        "stream": True,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    for attempt in range(1, retries + 1):
        try:
            chunks: list[str] = []
            with httpx.Client(trust_env=False, timeout=timeout_sec, follow_redirects=False) as client:
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
            l.warning(f"[skill] {label} attempt {attempt}/{retries} failed: {e}")
            if attempt == retries or _is_fatal_status(e):
                raise
            delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
            if _should_retry(e):
                l.info(f"[skill] {label} backoff {delay}s (429/5xx)")
            else:
                l.info(f"[skill] {label} non-retryable error, backing off {delay}s")
            time.sleep(delay)
    return ""


def call_aigocode(
    system: str,
    user: str,
    cfg: dict,
    retries: int = 3,
    log: logging.Logger | None = None,
) -> str:
    """Call aigocode API with SSE streaming (non-streaming drops content)."""
    return call_anthropic_stream(
        system=system,
        user=user,
        endpoint=resolve_env(cfg["endpoint"]),
        api_key=resolve_env(cfg["api_key"]),
        model=cfg["models"]["opus"],
        timeout_sec=cfg.get("timeout_sec", 120),
        retries=retries,
        log=log,
        label="aigocode",
    )


def call_gemini_flash(
    system: str,
    user: str,
    cfg: dict,
    retries: int = 3,
    log: logging.Logger | None = None,
) -> str:
    """
    Call Gemini Flash via 灵雅 (L0_API_ENDPOINT) — Anthropic-compatible /v1/messages.
    Switched from Google REST API to 灵雅 to avoid 429 rate limits (2026-04-15).
    """
    return call_anthropic_stream(
        system=system,
        user=user,
        endpoint=resolve_env(cfg["endpoint"]),
        api_key=resolve_env(cfg["api_key"]),
        model=cfg["models"]["flash"],
        timeout_sec=cfg.get("timeout_sec", 60),
        retries=retries,
        log=log,
        label="lingya_flash",
    )


def call_lingya_opus(
    system: str,
    user: str,
    cfg: dict,
    retries: int = 3,
    log: logging.Logger | None = None,
) -> str:
    """Call Claude Opus via 灵雅 (L0_API_ENDPOINT) with SSE streaming."""
    return call_anthropic_stream(
        system=system,
        user=user,
        endpoint=resolve_env(cfg["endpoint"]),
        api_key=resolve_env(cfg["api_key"]),
        model=cfg["models"]["opus"],
        timeout_sec=cfg.get("timeout_sec", 120),
        retries=retries,
        log=log,
        label="lingya_opus",
    )


def call_llm(
    skill: str,
    user_text: str,
    cfg: dict,
    log: logging.Logger,
    language: str = "zh",
) -> str:
    """Call the appropriate LLM for a skill.

    For Skill D, 'language' selects zh/en prompt variant.
    """
    if skill == "d":
        system = SKILL_D_PROMPTS.get(language, SKILL_D_PROMPTS["en"])
    else:
        system = SKILL_PROMPTS[skill]
    provider = SKILL_MODELS[skill]
    if provider == "lingya_opus":
        return call_lingya_opus(system, user_text, cfg["lingya_opus"], log=log)
    elif provider == "aigocode":
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
    p.add_argument("--no-secondary-filter", dest="secondary_filter",
                   action="store_false", default=True,
                   help="Disable secondary regex pre-filter (Skill A and D)")
    p.add_argument("--books-yaml", default=None,
                   help="Path to books.yaml (for Skill D language lookup)")
    p.add_argument("--clean-progress", action="store_true",
                   help="Remove error pages from _progress.json so --resume reprocesses them")
    p.add_argument("--circuit-breaker", type=int, default=5,
                   help="Abort after N consecutive failures (default: 5)")
    return p.parse_args()

def main() -> None:
    args = parse_args()
    skill = args.skill
    cfg = load_api_config()

    # ── --clean-progress mode: strip error pages from _progress.json ──
    if args.clean_progress:
        if not args.book_id:
            print("ERROR: --clean-progress requires --book-id", file=sys.stderr)
            sys.exit(1)
        _clean_dir = REPO_ROOT / "output" / args.book_id / f"skill_{skill}"
        _results_path  = _clean_dir / "results.jsonl"
        _progress_path = _clean_dir / "_progress.json"
        if not _results_path.exists():
            print(f"No results.jsonl found at {_results_path}")
            sys.exit(0)
        error_pages: set[int] = set()
        for line in _results_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if "_error" in rec and "_page" in rec:
                    error_pages.add(int(rec["_page"]))
            except Exception:
                pass
        if not error_pages:
            print(f"[clean-progress] No error pages found in results.jsonl — nothing to clean.")
            sys.exit(0)
        prog: dict = {}
        if _progress_path.exists():
            try:
                prog = json.loads(_progress_path.read_text())
            except Exception:
                prog = {}
        done_before = set(prog.get("done_pages", []))
        done_after  = done_before - error_pages
        removed     = done_before & error_pages
        prog["done_pages"]  = sorted(done_after)
        prog["done"]        = len(done_after)
        prog["cleaned_errors"] = sorted(removed)
        prog["updated_at"]  = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _progress_path.write_text(json.dumps(prog, indent=2))
        print(f"[clean-progress] {args.book_id}/skill_{skill}: "
              f"removed {len(removed)} error pages from done_pages. "
              f"Was {len(done_before)}, now {len(done_after)}.")
        print(f"  Cleaned pages: {sorted(removed)[:20]}{'...' if len(removed)>20 else ''}")
        sys.exit(0)

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

    # Load book language for Skill D prompt selection
    book_language = "zh"  # default fallback
    if skill == "d":
        try:
            yaml_path = Path(args.books_yaml) if args.books_yaml else (REPO_ROOT / "config" / "books.yaml")
            with open(yaml_path) as _f:
                _books = yaml.safe_load(_f)
            if isinstance(_books, list):
                _entry = next((b for b in _books if b.get("id") == book_id), None)
                if _entry:
                    book_language = _entry.get("language", "zh")
        except Exception as _e:
            log.warning(f"Could not load book language: {_e}")
        log.info(f"Skill D language: {book_language}")

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
    consecutive_failures = 0
    _circuit_threshold = args.circuit_breaker

    t0 = time.time()
    for i, sig in enumerate(todo):
        page_num = sig["page"]
        page_text = pages_map.get(page_num, "")

        if not page_text.strip():
            log.info(f"  page {page_num}: empty, skipping")
            done_pages.add(page_num)
            continue

        # Skill A: secondary regex filter (zero-cost, pre-Opus FP reduction)
        if skill == "a" and args.secondary_filter:
            from secondary_filter import filter_skill_a as _filter_a
            _keep, _reason = _filter_a(page_text, sig)
            if not _keep:
                log.info(f"  page {page_num}: secondary_filter_a skipped ({_reason})")
                results_file.write(json.dumps({
                    "_page": page_num, "_skill": skill, "_book": book_id,
                    "_filtered": True, "_filter_reason": _reason
                }, ensure_ascii=False) + '\n')
                done_pages.add(page_num)
                continue

        if skill == "d" and args.secondary_filter:
            from secondary_filter import secondary_filter_d as _filter_d
            if not _filter_d(page_text, book_language):
                log.info(f"  page {page_num}: secondary_filter_d skipped (no aesthetic terms)")
                results_file.write(json.dumps({
                    "_page": page_num, "_skill": skill, "_book": book_id,
                    "_filtered": True, "_filter_reason": "filter_d_no_aesthetic"
                }, ensure_ascii=False) + '\n')
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
            raw_response = call_llm(skill, user_msg, cfg, log, language=book_language)
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
            if _is_fatal_status(e):
                # 401/403: auth error — abort entire run, do NOT mark page done
                log.error(
                    f"  page {page_num}: FATAL AUTH {e.response.status_code} — "
                    f"aborting run. Check API key / quota."
                )
                failed += 1
                results_file.write(json.dumps({
                    "_page": page_num, "_skill": skill,
                    "_error": f"auth_{e.response.status_code}", "_book": book_id,
                }, ensure_ascii=False) + "\n")
                results_file.flush()
                save_progress(out_dir, done_pages, total, failed)
                results_file.close()
                log.error("Run aborted. Fix API key then re-run with --resume to continue.")
                sys.exit(1)
            else:
                log.error(f"  page {page_num}: API error: {e}")
                failed += 1
                consecutive_failures += 1
                results_file.write(json.dumps({
                    "_page": page_num, "_skill": skill, "_error": str(e), "_book": book_id,
                }, ensure_ascii=False) + "\n")
                # Circuit breaker: abort after N consecutive failures
                if consecutive_failures >= _circuit_threshold:
                    results_file.flush()
                    save_progress(out_dir, done_pages, total, failed)
                    results_file.close()
                    log.critical(
                        f"CIRCUIT BREAKER TRIPPED: {consecutive_failures} consecutive failures "
                        f"(threshold={_circuit_threshold}). Last error: {e}. "
                        f"Aborting to prevent further API waste."
                    )
                    sys.exit(1)
        else:
            # try succeeded (no exception) — mark page done and reset failure counter
            consecutive_failures = 0
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
