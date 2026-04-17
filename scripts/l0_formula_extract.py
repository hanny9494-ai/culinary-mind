#!/usr/bin/env python3
"""
L0 公式提取 MVP Pipeline — Steps 1, 2, 3
========================================
Step 1: Regex candidate filtering (no LLM, zero cost)
Step 2: 9b binary classification via Ollama (local, zero cost)
Step 3: Opus formula extraction via Lingya API (3 concurrent)

Usage:
    python3 scripts/l0_formula_extract.py [--step 1|2|3|all] [--limit N] [--dry-run]

Long-running note: for Step 2/3, run with:
    caffeinate -s nohup python3 scripts/l0_formula_extract.py --step 2 &
"""

# ── Clear proxy env vars first (local proxy 127.0.0.1:7890 must be bypassed) ──
import os
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import re
import sys
import json
import time
import asyncio
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Iterator

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "output" / "l0_computable"
CANDIDATES_FILE = OUTPUT_DIR / "mvp_candidates.jsonl"
CLASSIFIED_FILE = OUTPUT_DIR / "mvp_classified.jsonl"
FORMULAS_FILE = OUTPUT_DIR / "mvp_formulas.jsonl"
STEP2_PROGRESS = OUTPUT_DIR / "step2_progress.json"
STEP3_PROGRESS = OUTPUT_DIR / "step3_progress.json"

# ── Target domains for煎牛排 + 炸鸡煳 ──────────────────────────────────────────
TARGET_DOMAINS = {
    "thermal_dynamics",
    "protein_science",
    "texture_rheology",
    "lipid_science",
    "carbohydrate",
    "maillard_caramelization",
    "water_activity",
}

# ── Step 1 filter keywords (case-insensitive) ─────────────────────────────────
CONTENT_KEYWORDS = re.compile(
    r"°[CF]|%|ratio|rate|equation|kinetics|activation|constant|threshold|onset|"
    r"denaturation|gelatinization|\bTg\b|\bAw\b|denature|maillard|browning|viscosity|"
    r"diffusion|conductivity|enthalpy|latent|evaporation|absorption|gelatin|collagen|"
    r"myosin|actin|\bstarch\b|gluten|crisp|crust|Q10|Arrhenius",
    re.IGNORECASE,
)

QUOTE_FORMULA_MARKERS = re.compile(
    r"=|formula|law|coefficient|\bk\s*=|\brate\s*=|Q10|Arrhenius|Fick|Fourier|Henry",
    re.IGNORECASE,
)

DIGIT_RE = re.compile(r"\d")

# ── Opus system prompts ───────────────────────────────────────────────────────
TRACK_B_PROMPT = """You are an expert Scientific Knowledge Extractor. Your task is to analyze scientific statements and citation quotes, and extract underlying mathematical formulas or physical laws into a strict JSON format.

## Extraction Rules & SymPy Syntax
1. **Chain of Thought (CoT)**: Always write your reasoning in the `reasoning` field BEFORE extracting the formula. Analyze if a formula exists, identify its components, and determine if it's complete or partial.
2. **Formula Types**:
   - "scientific_law": Pure physical/chemical relationships.
   - "empirical_rule": Culinary rules of thumb and operational heuristics.
   - "threshold_constant": Critical temperature points, pH levels, or state-change thresholds. Use Eq() for these. Example: "Ovotransferrin denatures at 61°C" → sympy_expression: "Eq(T_denature_ovotransferrin, 61)"
   - If no mathematical relationship is stated or strongly implied, set has_formula: false.
3. **SymPy strict syntax**:
   - Use ** for exponentiation, NEVER use ^ (e.g., x**2, not x^2).
   - Use exp() for exponential functions, NEVER use e**x or e^x (e.g., A * exp(-Ea / (R * T))).
   - For conditional formulas, use Piecewise: Piecewise((expr1, cond1), (expr2, cond2)).
   - For thresholds/constants, use Eq(): Eq(symbol, value).
4. **Symbol Classification**:
   - variables: State variables that change over time/space (e.g., Temperature T, Time t, Concentration C).
   - parameters: Condition-specific inputs or boundary conditions (e.g., target temperature 130°C, initial mass).
   - constants: Universal or material-specific fixed values (e.g., Ideal Gas Constant R, activation energy Ea).
5. **Units**: NEVER convert units. Keep the exact units mentioned in the text.
6. **Partial formulas**: If the text implies a known relationship but omits specific constants, use readable placeholders (e.g., k_placeholder, Ea_placeholder). Use formula_type "scientific_law" or "empirical_rule" as appropriate; note partial nature in reasoning.
7. **ANTI-HALLUCINATION**: Do NOT fill in constants from your pre-training knowledge. Only use values explicitly stated in the text. Missing values MUST use _placeholder suffix.

## Output Format
CRITICAL: You must output ONLY valid, raw JSON. Do NOT wrap the JSON in markdown code blocks (NO ```json). Your response must begin strictly with the { character and end with }.

Output schema:
{
  "has_formula": boolean,
  "reasoning": "Step-by-step analysis of the text...",
  "formula_type": "scientific_law" | "empirical_rule" | "threshold_constant" | null,
  "formula_name": string | null,
  "sympy_expression": string | null,
  "symbols": {
    "variables": [{"symbol": "string", "description": "string", "unit": "string or null"}],
    "parameters": [{"symbol": "string", "description": "string", "unit": "string or null"}],
    "constants": [{"symbol": "string", "description": "string", "unit": "string or null"}]
  }
}"""

TRACK_A_PROMPT = """You are an expert Food Engineering and Thermodynamics Extractor.
Your task is to analyze engineering textbook chunks and extract strictly mathematical relationships
(PDEs, ODEs, algebraic laws, empirical correlations, thermophysical property tables).

## Role Definitions (CRITICAL)
- **state** = computed output / dependent variable that the formula solves for (e.g., T, C, v)
- **parameter** = user-supplied input / independent variable that drives the calculation (e.g., T_env, h_conv, moisture_content)
- **constant** = fixed physical constant that never changes (e.g., R=8.314, g=9.81, σ=5.67e-8)

Do NOT extract:
- Cooking doneness thresholds ("beef is done at 63°C") — these are threshold_constants, not engineering equations
- Qualitative causal chains ("higher temperature causes faster reaction")
- Dimensionless numbers without their full correlation equation

## MotherFormula Matching (REQUIRED)
Every extracted formula MUST be matched to one of the 53 registered MotherFormulas below.
Use the exact `formula_id` string. If no match, set formula_id to "NEW" and justify in reasoning.

53 REGISTERED MOTHERFORMULAS:
MF_001: Fourier Heat Conduction — ∂T/∂t = α·∂²T/∂x² — domain: thermal_dynamics
MF_002: Choi-Okos Model — Cp = Σ(Xi·Cpi(T)) — domain: thermal_dynamics
MF_003: Newton's Law of Cooling — q = h·A·(Ts − T_env) — domain: thermal_dynamics
MF_004: Stefan-Boltzmann Law — q = ε·σ·A·T⁴ — domain: thermal_dynamics
MF_005: Latent Heat of Vaporization — q_vap = m_dot·h_fg — domain: thermal_dynamics
MF_006: Nusselt Number Correlation — Nu = c·Re^m·Pr^n — domain: thermal_dynamics
MF_007: Heat Transfer Biot Number — Bi = (h·L)/k — domain: thermal_dynamics
MF_008: Arrhenius Equation — k = A·exp(−Ea/(RT)) — domain: maillard_caramelization, protein_science
MF_009: D/Z/F Value Model — F = D·(log10(N0)−log10(Nt)) — domain: food_safety
MF_010: Michaelis-Menten Kinetics — v = (v_max·[S])/(Km+[S]) — domain: enzyme
MF_011: Monod Equation — μ = (μ_max·[S])/(Ks+[S]) — domain: fermentation
MF_012: Gompertz Growth Model — y(t) = a·exp(−exp(b−c·t)) — domain: food_safety
MF_013: Avrami Equation — X(t) = 1−exp(−k·t^n) — domain: carbohydrate
MF_014: Fick's Second Law — ∂C/∂t = D·∂²C/∂x² — domain: mass_transfer
MF_015: GAB Isotherm Equation — X = (Xm·C·K·aw)/((1−K·aw)(1−K·aw+C·K·aw)) — domain: water_activity
MF_016: Gordon-Taylor Equation — Tg = (w1·Tg1+k·w2·Tg2)/(w1+k·w2) — domain: texture_rheology
MF_017: Henderson-Hasselbalch Equation — pH = pKa + log10([A−]/[HA]) — domain: salt_acid_chemistry
MF_018: Nernst Equation — E = E0−(RT/zF)·ln(Q) — domain: oxidation_reduction
MF_019: Antoine Equation — log10(P) = A−B/(T+C) — domain: aroma_volatiles
MF_020: Power Law Model — τ = K·(γ_dot)^n — domain: texture_rheology
MF_021: Herschel-Bulkley Model — τ = τ0 + K·(γ_dot)^n — domain: texture_rheology
MF_022: Casson Plastic Model — sqrt(τ) = sqrt(τ0) + sqrt(η_p·γ_dot) — domain: texture_rheology
MF_023: WLF Equation — log10(aT) = −C1·(T−Tg)/(C2+T−Tg) — domain: texture_rheology
MF_024: Weber-Fechner Law — R = k·log10(S/S0) — domain: taste_perception
MF_025: Odor Activity Value (OAV) — OAV = Ci/T_threshold_i — domain: aroma_volatiles
MF_026: Gas-Liquid Partition Coefficient — Ki = C_gas_i/C_liquid_i — domain: aroma_volatiles
MF_027: Buffer Capacity (Van Slyke) — β = 2.303·(Kw/[H+]+[H+]+([C]·Ka·[H+])/(Ka+[H+])²) — domain: salt_acid_chemistry
MF_028: Young-Laplace Equation — ΔP = γ·(1/R1+1/R2) — domain: texture_rheology
MF_029: Nusselt Number Film Condensation — h_avg = 0.943·((k³·ρ·(ρ−ρv)·g·hfg)/(L·μ·(Tsat−Ts)))^0.25 — domain: thermal_dynamics
MF_030: Leidenfrost Equation — q_film = h_film·(Tw−Tsat) — domain: thermal_dynamics
MF_031: Peleg's Extraction Model — M(t) = M0 + t/(k1+k2·t) — domain: mass_transfer
MF_032: DLVO Colloidal Stability — V_total = V_A + V_R — domain: lipid_science
MF_033: Stokes' Law — v = (2·g·r²·(ρp−ρf))/(9·η) — domain: mass_transfer
MF_034: Lumry-Eyring Protein Denaturation — N <-> U -> A (ODE system) — domain: protein_science
MF_035: Damköhler Number — Da = ReactionRate/DiffusionRate — domain: cross_domain
MF_036: Flory-Huggins Solution Theory — ΔG_mix = RT·(n1·lnφ1+n2·lnφ2+χ·n1·φ2) — domain: carbohydrate
MF_037: van't Hoff Osmotic Pressure — Π = i·C·R·T — domain: water_activity
MF_038: Poroelasticity (Biot) — ∇·G∇u+∇(λ+G)∇·u−α∇p = 0 — domain: texture_rheology
MF_039: Biot Number for Mass Transfer — Bi_m = (hm·L)/D_eff — domain: mass_transfer
MF_040: Kubelka-Munk Theory — K/S = (1−R_inf)²/(2·R_inf) — domain: color_pigment
MF_041: Washburn's Equation — L² = (γ·rc·cosθ/(2η))·t — domain: mass_transfer
MF_042: Clausius-Clapeyron Equation — ln(P2/P1) = (ΔHvap/R)·(1/T1−1/T2) — domain: thermal_dynamics
MF_043: Lambert's Law for Microwave — P(z) = P0·exp(−2αz) — domain: equipment_physics
MF_044: Kedem-Katchalsky Equations — Jv = Lp·(ΔP−σ·ΔΠ) — domain: mass_transfer
MF_045: Griffith Fracture Theory — σf = sqrt((2·E·γ)/(π·a)) — domain: texture_rheology
MF_046: Rayleigh-Plesset Equation — R·d²R/dt²+(3/2)·(dR/dt)² = (Pb−Pinf−2γ/R)/ρ — domain: equipment_physics
MF_047: Reynolds Number — Re = (ρ·v·L)/μ — domain: cross_domain
MF_048: Schmidt Number — Sc = μ/(ρ·D) — domain: cross_domain
MF_049: Grashof Number — Gr = (g·β·(Ts−T_inf)·L³)/ν² — domain: thermal_dynamics
MF_050: Raoult's Law — Pi = xi·Pi_star — domain: aroma_volatiles
MF_051: Marangoni Effect — τ = dγ/dx — domain: texture_rheology
MF_052: Hertzian Contact Theory — a = ((3·F·R)/(4·E_star))^(1/3) — domain: texture_rheology
MF_053: Beidler Receptor Binding — R = (Rmax·C)/(Kd+C) — domain: taste_perception

## SymPy Syntax Rules
- Use ** for exponentiation (NEVER ^)
- Use exp() for exponential (NEVER e**x)
- ALL formulas must be wrapped in Eq(dependent_var, expression) — NO bare expressions
  ✅ Correct: "Eq(k, A * exp(-Ea / (R * T)))"
  ❌ Wrong: "A * exp(-Ea / (R * T))"
- For thresholds: Eq(T_denature_myosin, 50)
- For conditionals: Piecewise((expr1, cond1), (expr2, cond2))

## Output Format
CRITICAL: Output ONLY valid raw JSON starting with { — no markdown fences.

{
  "has_formula": boolean,
  "formula_id": "MF_XXX" | "NEW",
  "reasoning": "Step-by-step: what formula this is, which MF it matches (or why NEW), what role each symbol plays",
  "formula_type": "scientific_law" | "empirical_rule" | "threshold_constant" | null,
  "formula_name": string | null,
  "sympy_expression": "Eq(dependent_var, expression_in_sympy_syntax)" | null,
  "symbols": {
    "variables": [{"symbol": "string", "description": "string", "unit": "string or null", "role": "state"}],
    "parameters": [{"symbol": "string", "description": "string", "unit": "string or null", "role": "parameter"}],
    "constants": [{"symbol": "string", "description": "string", "unit": "string or null", "role": "constant", "value": number_or_null}]
  },
  "applicable_range": {"variable_name": {"min": number, "max": number, "unit": "string"}}
}
CRITICAL: You must output ONLY valid, raw JSON. Do NOT wrap the JSON in markdown code blocks."""


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Candidate filtering
# ══════════════════════════════════════════════════════════════════════════════

def iter_stage4_entries() -> Iterator[dict]:
    """Yield all entries from all stage4_*/stage4_deduped.jsonl files."""
    stage4_dirs = sorted(REPO_ROOT.glob("output/stage4_*/"))
    # Also check output/stage4/ (the merged file)
    merged = REPO_ROOT / "output" / "stage4" / "stage4_deduped.jsonl"

    files = []
    for d in stage4_dirs:
        jsonl = d / "stage4_deduped.jsonl"
        if jsonl.exists():
            files.append((d.name, jsonl))
    if merged.exists():
        files.append(("stage4_merged", merged))

    for book_name, fpath in files:
        with open(fpath, encoding="utf-8") as f:
            for line_idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Assign id if missing
                if "id" not in entry:
                    # Remove "stage4_" prefix for cleaner id
                    clean_name = book_name.replace("stage4_", "")
                    entry["id"] = f"{clean_name}_{line_idx:06d}"
                entry["source_book"] = book_name
                yield entry


def matches_step1_filter(entry: dict) -> bool:
    """Return True if entry is a candidate for formula extraction."""
    domain = entry.get("domain", "")
    if domain not in TARGET_DOMAINS:
        return False

    stmt = entry.get("scientific_statement", "") or ""
    quote = entry.get("citation_quote", "") or ""
    combined = stmt + " " + quote

    # Must contain digits somewhere
    has_digits = bool(DIGIT_RE.search(combined))

    # Primary: digits + domain keyword in content
    if has_digits and CONTENT_KEYWORDS.search(combined):
        return True

    # Secondary: formula marker in citation quote
    if QUOTE_FORMULA_MARKERS.search(quote):
        return True

    return False


def run_step1(limit: int = 0, dry_run: bool = False) -> int:
    """Step 1: Regex filter. Returns count of candidates."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("STEP 1: Candidate filtering")
    print("=" * 60)

    candidates = []
    total_scanned = 0

    for entry in iter_stage4_entries():
        total_scanned += 1
        if matches_step1_filter(entry):
            candidates.append(entry)
        if limit and total_scanned >= limit:
            break
        if total_scanned % 5000 == 0:
            print(f"  Scanned {total_scanned:,} entries, found {len(candidates):,} candidates...")

    print(f"\nScanned {total_scanned:,} total entries")
    print(f"Found {len(candidates):,} candidates in target domains")

    if dry_run:
        print("[dry-run] Skipping write")
        if candidates:
            print(f"\nSample candidate:")
            print(json.dumps(candidates[0], ensure_ascii=False, indent=2)[:500])
        return len(candidates)

    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"Saved → {CANDIDATES_FILE}")
    return len(candidates)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: 9b binary classification via Ollama
# ══════════════════════════════════════════════════════════════════════════════

def call_ollama_9b(stmt: str, quote: str) -> bool:
    """Call Ollama qwen3.5:9b. Returns True if has computable relation."""
    prompt = (
        "Does this scientific statement contain a computable mathematical relationship "
        "where one variable depends on another (like a formula, equation, rate law, or "
        "threshold constant)? Answer only YES or NO.\n\n"
        f"Statement: {stmt}\n"
        f"Context: {quote}"
    )

    payload = json.dumps({
        "model": "qwen2.5:7b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 20},
    }).encode()

    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            response_text = result.get("response", "").strip().upper()
            if response_text:
                return response_text.startswith("YES")
            # Fallback: check thinking field (qwen3.5 thinking mode)
            thinking = result.get("thinking", "").strip().upper()
            return "YES" in thinking[-100:]
    except Exception as e:
        print(f"  [Ollama error] {e}", file=sys.stderr)
        return False


def run_step2(limit: int = 0, dry_run: bool = False) -> tuple[int, int]:
    """Step 2: 9b classification. Returns (total, classified_true)."""
    if not CANDIDATES_FILE.exists():
        print("ERROR: mvp_candidates.jsonl not found. Run Step 1 first.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("STEP 2: 9b binary classification (Ollama qwen3.5:9b)")
    print("=" * 60)

    # Load resume state
    processed_ids: set[str] = set()
    if STEP2_PROGRESS.exists():
        try:
            prog = json.loads(STEP2_PROGRESS.read_text())
            processed_ids = set(prog.get("processed_ids", []))
            print(f"  Resuming: {len(processed_ids)} already processed")
        except Exception:
            pass

    # Load all candidates
    candidates = []
    with open(CANDIDATES_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    candidates.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    print(f"  Loaded {len(candidates):,} candidates")

    if limit:
        candidates = candidates[:limit]

    # Load already-classified results for dedup
    existing: dict[str, dict] = {}
    if CLASSIFIED_FILE.exists():
        with open(CLASSIFIED_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        e = json.loads(line)
                        existing[e["id"]] = e
                    except Exception:
                        continue

    count_true = sum(1 for e in existing.values() if e.get("has_computable_relation"))

    with open(CLASSIFIED_FILE, "a", encoding="utf-8") as outf:
        for idx, entry in enumerate(candidates):
            eid = entry["id"]
            if eid in processed_ids:
                continue

            if dry_run:
                print(f"  [dry-run] Would classify: {eid}")
                if idx >= 5:
                    print(f"  [dry-run] ... and {len(candidates) - 6} more")
                    break
                continue

            stmt = entry.get("scientific_statement", "") or ""
            quote = entry.get("citation_quote", "") or ""

            result = call_ollama_9b(stmt, quote)
            entry["has_computable_relation"] = result

            if result:
                count_true += 1

            outf.write(json.dumps(entry, ensure_ascii=False) + "\n")
            processed_ids.add(eid)

            # Save progress every 50 entries
            if len(processed_ids) % 50 == 0:
                STEP2_PROGRESS.write_text(json.dumps({"processed_ids": list(processed_ids)}))
                print(f"  [{idx+1}/{len(candidates)}] classified {len(processed_ids)} — {count_true} true")

        if not dry_run:
            STEP2_PROGRESS.write_text(json.dumps({"processed_ids": list(processed_ids)}))

    total = len(processed_ids)
    count_false = total - count_true
    print(f"\nClassification complete:")
    print(f"  Total classified: {total:,}")
    print(f"  has_computable_relation=true:  {count_true:,}")
    print(f"  has_computable_relation=false: {count_false:,}")
    return total, count_true


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Opus formula extraction via Lingya API
# ══════════════════════════════════════════════════════════════════════════════

def build_opus_user_message(entry: dict) -> str:
    stmt = entry.get("scientific_statement", "")
    conditions = entry.get("boundary_conditions", [])
    quote = entry.get("citation_quote", "")
    return (
        f"Please extract the formula from the following input:\n"
        f"- scientific_statement: {stmt}\n"
        f"- boundary_conditions: {conditions}\n"
        f"- citation_quote: {quote}"
    )


def parse_opus_response(raw: str) -> dict | None:
    """Strip markdown fences and parse JSON from Opus response."""
    raw = raw.strip()
    # Strip markdown code fences
    if raw.startswith("```"):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
    # Also try to find JSON object if response has prefix text
    if not raw.startswith("{"):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def call_opus_async(session, endpoint: str, api_key: str, entry: dict, system_prompt: str) -> dict | None:
    """Call Opus via Lingya API asynchronously. Returns parsed formula dict or None."""
    try:
        import aiohttp as _aiohttp
    except ImportError:
        return call_opus_sync(endpoint, api_key, entry, system_prompt)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "claude-opus-4-5",
        "max_tokens": 2000,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": build_opus_user_message(entry)}],
    }

    try:
        async with session.post(
            f"{endpoint}/messages",
            headers=headers,
            json=payload,
            timeout=_aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                print(f"  [Opus API error {resp.status}] {err_text[:200]}", file=sys.stderr)
                return None
            data = await resp.json()
            raw = data["content"][0]["text"]
            return parse_opus_response(raw)
    except Exception as e:
        print(f"  [Opus async error] {e}", file=sys.stderr)
        return None


def call_opus_sync(endpoint: str, api_key: str, entry: dict, system_prompt: str) -> dict | None:
    """Sync fallback for Opus API call using urllib."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    payload = json.dumps({
        "model": "claude-opus-4-5",
        "max_tokens": 2000,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": build_opus_user_message(entry)}],
    }).encode()

    req = urllib.request.Request(
        f"{endpoint}/messages",
        data=payload,
        headers=headers,
    )

    # Disable proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    try:
        with opener.open(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            raw = data["content"][0]["text"]
            return parse_opus_response(raw)
    except Exception as e:
        print(f"  [Opus sync error] {e}", file=sys.stderr)
        return None


async def run_step3_async(
    entries_to_process: list[dict],
    endpoint: str,
    api_key: str,
    outf,
    processed_ids: set[str],
    count_formulas: list,
    system_prompt: str,
) -> None:
    """Process entries 3 at a time with asyncio."""
    try:
        import aiohttp
        connector = aiohttp.TCPConnector(ssl=False)
        trust_env = False
        async with aiohttp.ClientSession(connector=connector, trust_env=trust_env) as session:
            semaphore = asyncio.Semaphore(3)

            async def process_one(entry: dict):
                async with semaphore:
                    eid = entry["id"]
                    formula = await call_opus_async(session, endpoint, api_key, entry, system_prompt)

                    if formula is None:
                        print(f"  [skip] {eid} — API error or null response")
                        processed_ids.add(eid)
                        return

                    entry_out = {k: v for k, v in entry.items()}
                    entry_out["formula"] = formula

                    if formula.get("has_formula"):
                        count_formulas.append(1)
                        outf.write(json.dumps(entry_out, ensure_ascii=False) + "\n")
                        outf.flush()
                        print(f"  ✓ {eid} [{formula.get('formula_type')}] {formula.get('formula_name', '')[:50]}")
                    else:
                        print(f"  ✗ {eid} — has_formula=false")

                    processed_ids.add(eid)
                    # Save progress periodically
                    if len(processed_ids) % 10 == 0:
                        STEP3_PROGRESS.write_text(
                            json.dumps({"processed_ids": list(processed_ids)})
                        )

            tasks = [process_one(e) for e in entries_to_process]
            await asyncio.gather(*tasks)

    except ImportError:
        # Sync fallback
        print("  [aiohttp not available, using sync mode]")
        for entry in entries_to_process:
            eid = entry["id"]
            formula = call_opus_sync(endpoint, api_key, entry, system_prompt)
            if formula and formula.get("has_formula"):
                count_formulas.append(1)
                entry_out = {k: v for k, v in entry.items()}
                entry_out["formula"] = formula
                outf.write(json.dumps(entry_out, ensure_ascii=False) + "\n")
                outf.flush()
                print(f"  ✓ {eid} [{formula.get('formula_type')}] {formula.get('formula_name', '')[:50]}")
            processed_ids.add(eid)
            time.sleep(0.2)  # rate limit


def run_step3(limit: int = 0, dry_run: bool = False, track: str = "B") -> int:
    """Step 3: Opus extraction. Returns count of extracted formulas."""
    if not CLASSIFIED_FILE.exists():
        print("ERROR: mvp_classified.jsonl not found. Run Step 2 first.")
        sys.exit(1)

    endpoint = os.environ.get("L0_API_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("L0_API_KEY", "")

    if not endpoint or not api_key:
        print("ERROR: L0_API_ENDPOINT and L0_API_KEY environment variables required.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f"STEP 3: Opus formula extraction (Lingya API, 3 concurrent) [Track {track.upper()}]")
    print("=" * 60)

    system_prompt = TRACK_A_PROMPT if track.upper() == "A" else TRACK_B_PROMPT

    # Load resume state
    processed_ids: set[str] = set()
    if STEP3_PROGRESS.exists():
        try:
            prog = json.loads(STEP3_PROGRESS.read_text())
            processed_ids = set(prog.get("processed_ids", []))
            print(f"  Resuming: {len(processed_ids)} already processed")
        except Exception:
            pass

    # Load classified entries with has_computable_relation=true
    to_process = []
    with open(CLASSIFIED_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("has_computable_relation") and e["id"] not in processed_ids:
                to_process.append(e)

    print(f"  Found {len(to_process):,} entries to extract")

    if limit:
        to_process = to_process[:limit]
        print(f"  Limited to {limit} entries")

    if dry_run:
        print(f"[dry-run] Would call Opus on {len(to_process)} entries")
        for e in to_process[:5]:
            print(f"  - {e['id']}: {e.get('scientific_statement', '')[:80]}")
        return 0

    if not to_process:
        # Count existing formulas
        count = sum(1 for _ in open(FORMULAS_FILE, encoding="utf-8")) if FORMULAS_FILE.exists() else 0
        print(f"  Nothing new to process. Existing formulas: {count}")
        return count

    count_formulas: list = []

    with open(FORMULAS_FILE, "a", encoding="utf-8") as outf:
        asyncio.run(run_step3_async(to_process, endpoint, api_key, outf, processed_ids, count_formulas, system_prompt))

    STEP3_PROGRESS.write_text(json.dumps({"processed_ids": list(processed_ids)}))

    # Count total
    total_formulas = 0
    if FORMULAS_FILE.exists():
        with open(FORMULAS_FILE, encoding="utf-8") as f:
            total_formulas = sum(1 for line in f if line.strip())

    print(f"\nExtraction complete:")
    print(f"  New formulas extracted this run: {len(count_formulas)}")
    print(f"  Total formulas in file: {total_formulas}")
    print(f"  Saved → {FORMULAS_FILE}")

    return total_formulas


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="L0 公式提取 MVP Pipeline (Steps 1-3)"
    )
    parser.add_argument(
        "--step",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Which step to run (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max entries to process (0 = unlimited)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without calling APIs",
    )
    parser.add_argument(
        "--track",
        choices=["A", "B", "a", "b"],
        default="B",
        help="Extraction track: A (Engineering Math) or B (Culinary Rules)",
    )
    args = parser.parse_args()

    step = args.step
    limit = args.limit
    dry_run = args.dry_run
    track = args.track.upper()

    if dry_run:
        print("[DRY RUN MODE — no APIs will be called, no files written]\n")

    if step in ("1", "all"):
        n = run_step1(limit=limit, dry_run=dry_run)
        if n == 0 and not dry_run:
            print("WARNING: No candidates found. Check domain filters and file paths.")

    if step in ("2", "all"):
        run_step2(limit=limit, dry_run=dry_run)

    if step in ("3", "all"):
        run_step3(limit=limit, dry_run=dry_run, track=track)

    print("\nDone.")


if __name__ == "__main__":
    main()
