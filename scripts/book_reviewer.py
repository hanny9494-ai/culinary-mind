#!/usr/bin/env python3
"""
scripts/book_reviewer.py
Books review web UI — Flask + inline HTML.

Lets Jeff eyeball each of the 91 entries in books.yaml, see signal
distribution + sample page text, and update the `skills` / `purpose`
fields.

Start:
    python scripts/book_reviewer.py        # binds 0.0.0.0:8080
    open http://localhost:8080
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
from pathlib import Path
from typing import Any

import yaml
from flask import Flask, abort, redirect, render_template_string, request, url_for

REPO_ROOT   = Path(__file__).resolve().parents[1]
BOOKS_YAML  = REPO_ROOT / "config" / "books.yaml"
OUTPUT_ROOT = REPO_ROOT / "output"

NEEDS_REVIEW: set[str] = {
    # Track D 候选 — cc-lead 筛选，Jeff 复核
    "mc_vol1", "mc_vol2", "mc_vol3", "mc_vol4",
    "food_lab", "science_good_cooking", "chocolates_confections", "science_of_chocolate",
    "professional_baking", "bread_hamelman", "molecular_gastronomy", "mouthfeel",
    "cooking_for_geeks", "modernist_pizza", "koji_alchemy", "noma_fermentation",
    "ratio", "essentials_food_science", "ofc", "flavorama",
    "science_of_spice", "salt_fat_acid_heat", "taste_whats_missing", "neurogastronomy",
    "ice_cream_flavor", "bread_science_yoshino", "dashi_umami", "flavor_bible",
    "professional_pastry_chef", "handbook_molecular_gastronomy", "bocuse_cookbook",
    "french_sauces", "japanese_cooking_tsuji", "jacques_pepin", "franklin_barbecue",
    "sous_vide_keller", "flavor_thesaurus", "charcuterie", "art_of_fermentation",
    "professional_chef", "flavor_equation", "french_patisserie", "phoenix_claws",
    "alinea_-_grant_achatz", "bouchon_-_thomas_keller", "core_-_clare_smyth",
    "crave", "daniel_my_french_cuisine_-_daniel_boulud",
    "dokumen.pub_the-whole-fish-cookbook-new-",
    "eleven_madison_park_the_cookbook_-_danie",
    "eleven_madison_park_the_next_chapter_紫色封",
    "f1749_manresa", "f2986_baltic",
    "japanese_farm_food_-_nancy_singleton_hac",
    "meat_illustrated_a_foolproof_guide_to_un",
    "momofuku", "organum_nature_texture_intensity_purity",
    "relae_a_book_of_ideas_-_christian_f_pugl",
    "the-french-laundry-cookbook-978157965126",
    "the_everlasting_meal_cookbook_leftovers_",
    "the_hand_and_flowers_cookbook",
    "vegetarian_flavor_bible",
    "shijing", "chuantong_yc", "gufa_yc",
    "zhujixiaoguan_6", "zhujixiaoguan_3", "zhujixiaoguan_4",
    "zhujixiaoguan_2", "zhujixiaoguan_v6b", "zhujixiaoguan_dimsim2",
    "fenbuxiangjiena_yc", "yuecan_zhenwei_meat",
    "guangdong_pengtiao_quanshu", "hk_yuecan_yanxi",
    "zhongguo_caipu_guangdong", "zhongguo_yinshi_meixueshi",
    "yuecan_wangliang", "xidage_xunwei_hk",
    "bourne_food_texture", "meilgaard_sensory_evaluation",
    "lawless_sensory_evaluation", "reineccius_flavor_chemistry",
}

ALL_PURPOSES = ["science+recipe", "recipe_only", "aesthetic_culture", "engineering_textbook"]
ALL_SKILLS   = ["A", "B", "C", "D"]

app = Flask(__name__)
log = logging.getLogger("book_reviewer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_yaml_lock = threading.Lock()


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_books() -> list[dict]:
    with open(BOOKS_YAML) as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise RuntimeError(f"{BOOKS_YAML}: expected list")
    return data


def save_books(books: list[dict]) -> None:
    tmp = BOOKS_YAML.with_suffix(".yaml.tmp")
    with open(tmp, "w") as f:
        yaml.safe_dump(books, f,
                       allow_unicode=True,
                       default_flow_style=False,
                       sort_keys=False)
    tmp.replace(BOOKS_YAML)


_signal_stats_cache: dict[str, dict] = {}


def signal_stats(book_id: str) -> dict:
    """Return {A_pct,B_pct,C_pct,D_pct,skip_pct,total} for a book."""
    if book_id in _signal_stats_cache:
        return _signal_stats_cache[book_id]
    path = OUTPUT_ROOT / book_id / "signals.json"
    if not path.exists():
        s = {"A_pct": None, "B_pct": None, "C_pct": None, "D_pct": None,
             "skip_pct": None, "total": 0}
        _signal_stats_cache[book_id] = s
        return s
    try:
        data = json.loads(path.read_text())
    except Exception:
        s = {"A_pct": None, "B_pct": None, "C_pct": None, "D_pct": None,
             "skip_pct": None, "total": 0}
        _signal_stats_cache[book_id] = s
        return s
    total = len(data) or 1
    cnt = {k: 0 for k in ALL_SKILLS}
    skip = 0
    for rec in data:
        sig = rec.get("signals") or {}
        for k in ALL_SKILLS:
            if sig.get(k):
                cnt[k] += 1
        if rec.get("skip_reason"):
            skip += 1
    stats = {
        "A_pct":    round(cnt["A"] / total * 100, 1),
        "B_pct":    round(cnt["B"] / total * 100, 1),
        "C_pct":    round(cnt["C"] / total * 100, 1),
        "D_pct":    round(cnt["D"] / total * 100, 1),
        "skip_pct": round(skip     / total * 100, 1),
        "total":    len(data),
    }
    _signal_stats_cache[book_id] = stats
    return stats


def results_counts(book_id: str) -> dict[str, int]:
    """Count lines in each skill's results.jsonl (quick gauge of extraction progress)."""
    out: dict[str, int] = {}
    for sk in ALL_SKILLS:
        p = OUTPUT_ROOT / book_id / f"skill_{sk.lower()}" / "results.jsonl"
        if p.exists():
            try:
                # fast line count
                with open(p) as f:
                    out[sk] = sum(1 for _ in f)
            except Exception:
                out[sk] = 0
        else:
            out[sk] = 0
    return out


def gate_summary(book_id: str) -> list[dict]:
    gates_dir = OUTPUT_ROOT / book_id / "gates"
    out: list[dict] = []
    if not gates_dir.exists():
        return out
    for f in sorted(gates_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            out.append({"name": f.stem, "passed": d.get("passed")})
        except Exception:
            out.append({"name": f.stem, "passed": None})
    return out


def sample_pages(book_id: str, n: int = 3, seed: int = 42) -> list[dict]:
    """Pick N pages (prefer ones with any signal on) and return {page,text,signals}."""
    sig_path = OUTPUT_ROOT / book_id / "signals.json"
    pg_path  = OUTPUT_ROOT / book_id / "pages.json"
    if not sig_path.exists() or not pg_path.exists():
        return []
    try:
        signals = json.loads(sig_path.read_text())
        pages   = json.loads(pg_path.read_text())
    except Exception:
        return []
    text_by_page = {p["page"]: p.get("text", "") for p in pages}
    candidates = [
        s for s in signals
        if any((s.get("signals") or {}).values())
        and not s.get("skip_reason")
    ]
    if not candidates:
        candidates = [s for s in signals if not s.get("skip_reason")]
    if not candidates:
        return []
    rng = random.Random(seed)
    picks = rng.sample(candidates, min(n, len(candidates)))
    out = []
    for s in picks:
        pn = s["page"]
        txt = (text_by_page.get(pn) or "")[:500]
        out.append({"page": pn, "text": txt, "signals": s.get("signals") or {}})
    return out


# ── Auto-recommendation ───────────────────────────────────────────────────────

def recommend_skills(purpose: str | None, stats: dict) -> list[str]:
    """Rule-based recommendation. Returns sorted list of A/B/C/D."""
    rec: list[str] = []
    if stats.get("A_pct") is None:
        return []
    if stats["A_pct"] >= 10 and purpose not in {"recipe_only", "aesthetic_culture"}:
        rec.append("A")
    if stats["B_pct"] >= 20:
        rec.append("B")
    if stats["C_pct"] >= 15:
        rec.append("C")
    if stats["D_pct"] >= 25:
        rec.append("D")
    return rec


# ── Templates ─────────────────────────────────────────────────────────────────

CSS = """
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 20px; color: #222; background: #fafafa; }
  h1 { font-size: 20px; margin: 0 0 15px 0; }
  h2 { font-size: 16px; margin: 20px 0 8px; }
  table { border-collapse: collapse; width: 100%; background: white; }
  th, td { border: 1px solid #ddd; padding: 5px 8px; font-size: 13px; text-align: left; }
  th { background: #eee; position: sticky; top: 0; }
  tr.needs-review { background: #fff8dc; }
  tr:hover { background: #f0f8ff; }
  a { color: #0366d6; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .bar-wrap { display: inline-block; width: 120px; height: 12px;
              background: #eee; position: relative; vertical-align: middle; }
  .bar { height: 12px; background: #4a90e2; }
  .bar.skip { background: #aaa; }
  .muted { color: #888; }
  .pill { display: inline-block; padding: 1px 6px; font-size: 11px;
          border-radius: 8px; background: #eef; margin-right: 3px; }
  .pill.rec  { background: #dfd; }
  .pill.miss { background: #fcc; }
  form { margin-top: 10px; }
  button, input[type=submit] { padding: 6px 12px; font-size: 13px; cursor: pointer; }
  .toolbar { margin-bottom: 10px; }
  .sample { background: white; border: 1px solid #ddd; padding: 10px;
            margin: 8px 0; font-family: monospace; font-size: 12px;
            white-space: pre-wrap; max-height: 250px; overflow-y: auto; }
  .flash { padding: 8px 12px; background: #dfd; border: 1px solid #9c9;
           margin-bottom: 10px; }
"""

INDEX_TEMPLATE = """
<!doctype html><html><head><title>Books Reviewer</title>
<meta charset="utf-8"><style>{{ css }}</style></head><body>
<h1>📚 Books Reviewer — {{ books|length }} books
  {% if flash %}<span class="flash">{{ flash }}</span>{% endif %}</h1>
<div class="toolbar">
  <a href="{{ url_for('index') }}">All</a> |
  <a href="{{ url_for('index', filter='needs_review') }}">Needs review</a> |
  <a href="{{ url_for('index', filter='mismatch') }}">Skills ≠ recommended</a>
  <form method="post" action="{{ url_for('batch_apply') }}" style="display:inline;margin-left:20px;">
    <button type="submit"
      onclick="return confirm('Overwrite skills for ALL books with recommendations?');">
      Apply all auto-recommendations
    </button>
  </form>
</div>
<table>
<tr><th>#</th><th>ID</th><th>Purpose</th><th>Skills (cur / rec)</th>
    <th>A%</th><th>B%</th><th>C%</th><th>D%</th><th>Skip%</th><th>Pages</th></tr>
{% for b in books %}
  {% set s = b._stats %}
  {% set rec = b._rec %}
  {% set cur = b.skills or [] %}
  <tr class="{% if b.id in needs_review %}needs-review{% endif %}">
    <td>{{ loop.index }}</td>
    <td><a href="{{ url_for('detail', book_id=b.id) }}">{{ b.id }}</a></td>
    <td>{{ b.purpose or '' }}</td>
    <td>
      {% for sk in ['A','B','C','D'] %}
        {% if sk in cur and sk in rec %}<span class="pill rec">{{ sk }}</span>
        {% elif sk in cur %}<span class="pill">{{ sk }}</span>
        {% elif sk in rec %}<span class="pill miss">+{{ sk }}</span>
        {% endif %}
      {% endfor %}
    </td>
    {% for k in ['A_pct','B_pct','C_pct','D_pct','skip_pct'] %}
      <td>{% if s[k] is none %}<span class="muted">—</span>
          {% else %}{{ s[k] }}<div class="bar-wrap"><div class="bar{% if k=='skip_pct' %} skip{% endif %}"
               style="width:{{ (s[k]/100*120)|round|int }}px"></div></div>
          {% endif %}</td>
    {% endfor %}
    <td>{{ s.total or '' }}</td>
  </tr>
{% endfor %}
</table>
</body></html>
"""

DETAIL_TEMPLATE = """
<!doctype html><html><head><title>{{ book.id }}</title>
<meta charset="utf-8"><style>{{ css }}</style></head><body>
<p><a href="{{ url_for('index') }}">← All books</a>
   {% if prev_id %}| <a href="{{ url_for('detail', book_id=prev_id) }}">← {{ prev_id }}</a>{% endif %}
   {% if next_id %}| <a href="{{ url_for('detail', book_id=next_id) }}">{{ next_id }} →</a>{% endif %}
</p>
<h1>{{ book.id }}
  {% if book.id in needs_review %}<span class="pill" style="background:#ffd">Needs review</span>{% endif %}
  {% if flash %}<span class="flash">{{ flash }}</span>{% endif %}
</h1>
<p><b>Title:</b> {{ book.title }} &nbsp; <b>Author:</b> {{ book.author }}
   &nbsp; <b>Language:</b> {{ book.language }}</p>
<p><b>OCR:</b> {{ book.ocr_status }} &nbsp;
   <b>Signal:</b> {{ book.signal_status }} &nbsp;
   <b>Pages:</b> {{ stats.total }}</p>

<h2>Signal distribution</h2>
<table style="max-width:600px">
<tr><th>Signal</th><th>Pct</th><th>Bar</th></tr>
{% for sk in ['A','B','C','D'] %}
  <tr><td>{{ sk }}</td><td>{{ stats[sk+'_pct'] }}</td>
      <td><div class="bar-wrap"><div class="bar"
          style="width:{{ (stats[sk+'_pct']/100*400)|round|int }}px"></div></div></td></tr>
{% endfor %}
<tr><td>Skip</td><td>{{ stats.skip_pct }}</td>
    <td><div class="bar-wrap"><div class="bar skip"
        style="width:{{ (stats.skip_pct/100*400)|round|int }}px"></div></div></td></tr>
</table>

<h2>Skills — current vs recommended</h2>
<p>Current: <b>{{ book.skills or [] }}</b> &nbsp;
   Recommended: <b>{{ recommended }}</b></p>

<form method="post" action="{{ url_for('save', book_id=book.id) }}">
  <label><b>Skills:</b></label>
  {% for sk in ['A','B','C','D'] %}
    <label style="margin-right:15px;">
      <input type="checkbox" name="skill_{{ sk }}" value="1"
        {% if sk in (book.skills or []) %}checked{% endif %}> {{ sk }}
      {% if sk in recommended %}<span class="muted">(rec)</span>{% endif %}
    </label>
  {% endfor %}
  <br><br>
  <label><b>Purpose:</b>
    <select name="purpose">
      <option value="">—</option>
      {% for p in all_purposes %}
        <option value="{{ p }}" {% if p == book.purpose %}selected{% endif %}>{{ p }}</option>
      {% endfor %}
    </select>
  </label>
  <br><br>
  <button type="submit">Save</button>
  <button type="submit" name="apply_rec" value="1">Apply recommendation &amp; save</button>
</form>

<h2>Skill status / extraction counts</h2>
<table style="max-width:600px">
<tr><th>Skill</th><th>Status</th><th>Records so far</th></tr>
{% for sk in ['A','B','C','D'] %}
  <tr><td>{{ sk }}</td>
      <td>{{ book.get('skill_' + sk.lower() + '_status', '—') }}</td>
      <td>{{ counts[sk] }}</td></tr>
{% endfor %}
</table>

{% if gates %}
<h2>Gates</h2>
<ul>{% for g in gates %}<li>{{ g.name }}: passed={{ g.passed }}</li>{% endfor %}</ul>
{% endif %}

<h2>Sample pages (3 random with any signal on)</h2>
{% for p in samples %}
  <div><b>Page {{ p.page }}</b> — signals: {{ p.signals }}</div>
  <pre class="sample">{{ p.text }}</pre>
{% else %}
  <p class="muted">No samples (signals.json or pages.json missing).</p>
{% endfor %}

</body></html>
"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    books = load_books()
    filt = request.args.get("filter", "")
    flash = request.args.get("flash", "")
    # enrich
    for b in books:
        bid = b.get("id", "")
        b["_stats"] = signal_stats(bid)
        b["_rec"] = recommend_skills(b.get("purpose"), b["_stats"])
    if filt == "needs_review":
        books = [b for b in books if b.get("id") in NEEDS_REVIEW]
    elif filt == "mismatch":
        books = [b for b in books
                 if set(b.get("skills") or []) != set(b["_rec"])
                 and b["_rec"]]
    return render_template_string(
        INDEX_TEMPLATE,
        css=CSS,
        books=books,
        needs_review=NEEDS_REVIEW,
        flash=flash,
    )


@app.route("/book/<book_id>")
def detail(book_id: str):
    books = load_books()
    ids = [b.get("id") for b in books]
    if book_id not in ids:
        abort(404)
    idx = ids.index(book_id)
    book = books[idx]
    stats = signal_stats(book_id)
    rec = recommend_skills(book.get("purpose"), stats)
    samples = sample_pages(book_id, n=3)
    counts = results_counts(book_id)
    gates = gate_summary(book_id)
    prev_id = ids[idx - 1] if idx > 0 else None
    next_id = ids[idx + 1] if idx < len(ids) - 1 else None
    flash = request.args.get("flash", "")
    return render_template_string(
        DETAIL_TEMPLATE,
        css=CSS,
        book=book,
        stats=stats,
        recommended=rec,
        samples=samples,
        counts=counts,
        gates=gates,
        prev_id=prev_id,
        next_id=next_id,
        all_purposes=ALL_PURPOSES,
        needs_review=NEEDS_REVIEW,
        flash=flash,
    )


@app.route("/book/<book_id>/save", methods=["POST"])
def save(book_id: str):
    with _yaml_lock:
        books = load_books()
        entry = next((b for b in books if b.get("id") == book_id), None)
        if entry is None:
            abort(404)

        if request.form.get("apply_rec"):
            rec = recommend_skills(entry.get("purpose"), signal_stats(book_id))
            entry["skills"] = rec
        else:
            new_skills = [sk for sk in ALL_SKILLS
                          if request.form.get(f"skill_{sk}") == "1"]
            entry["skills"] = new_skills

        purp = request.form.get("purpose") or None
        if purp is not None and purp != "":
            entry["purpose"] = purp

        save_books(books)
    log.info(f"Saved {book_id}: skills={entry['skills']} purpose={entry.get('purpose')}")
    return redirect(url_for("detail", book_id=book_id,
                            flash=f"Saved: skills={entry['skills']}"))


@app.route("/batch/apply-recommendations", methods=["POST"])
def batch_apply():
    with _yaml_lock:
        books = load_books()
        n = 0
        for b in books:
            rec = recommend_skills(b.get("purpose"), signal_stats(b.get("id", "")))
            if rec and set(b.get("skills") or []) != set(rec):
                b["skills"] = rec
                n += 1
        save_books(books)
    log.info(f"Batch apply: updated {n} books.")
    return redirect(url_for("index", flash=f"Updated {n} books with recommendations."))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
