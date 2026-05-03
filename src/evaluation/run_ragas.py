"""Y-S1-3: RAGAS evaluation scaffold for the Y-system retrieval API.

Judge model: Lingya Gemini 3.1 Pro (avoids self-bias — Y-system answers are Claude).
Runs 4 RAGAS metrics: Context Precision, Context Recall, Faithfulness, Answer Relevancy.

Usage:
  python -m src.evaluation.run_ragas dummy
  python -m src.evaluation.run_ragas eval_set.json --output results.json

Input JSON format:
  [{"question": "...", "ground_truth": "..."},  ...]

Output:
  {"context_precision": 0.xx, "context_recall": 0.xx,
   "faithfulness": 0.xx, "answer_relevancy": 0.xx, "per_question": [...]}
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"

import httpx

try:
    from scripts._lingya_chat import post_lingya_chat
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts._lingya_chat import post_lingya_chat

RETRIEVAL_API_URL = os.getenv("RETRIEVAL_API_URL", "http://localhost:8760")
LINGYA_TIMEOUT_SECONDS = 600
LINGYA_MAX_RETRIES = 3
LINGYA_BACKOFF_SECONDS = (5, 15, 45)

# ── Judge model: Lingya Gemini (avoids self-bias vs Claude-generated answers) ─
L0_API_KEY     = os.environ.get("L0_API_KEY", "")
LINGYA_API_URL = f"{os.environ.get('L0_API_ENDPOINT', '').rstrip('/')}/v1"
JUDGE_MODEL    = os.getenv("JUDGE_MODEL", "gemini-3.1-pro-preview-thinking")

# Configurable via config/evaluation.yaml (loaded at startup if present)
REPO_ROOT = Path(__file__).resolve().parents[2]

def load_eval_config() -> dict:
    cfg_path = REPO_ROOT / "config" / "evaluation.yaml"
    if cfg_path.exists():
        try:
            import yaml
            return yaml.safe_load(cfg_path.read_text()) or {}
        except ImportError:
            pass
    return {}


# ── Dummy data ────────────────────────────────────────────────────────────────

DUMMY_QUESTIONS = [
    {
        "question": "为什么烤鸡胸柴？",
        "ground_truth": "鸡胸肌纤维在65°C以上大量变性收缩，同时肌红蛋白流失导致水分散逸，造成口感发柴。",
    },
    {
        "question": "美拉德反应需要什么条件？",
        "ground_truth": "美拉德反应需要氨基酸和还原糖同时存在，温度通常需达到140°C以上，低水分环境有利于反应发生。",
    },
    {
        "question": "为什么腌制肉类加盐能保水？",
        "ground_truth": "盐离子使肌肉蛋白（肌球蛋白）部分解链展开，增大持水力；同时盐水渗透压使肌肉细胞吸水膨胀。",
    },
    {
        "question": "面团中筋性如何形成？",
        "ground_truth": "面粉中麦醇溶蛋白和麦谷蛋白遇水后通过二硫键和氢键交联，形成连续的谷蛋白网络，即麸质（gluten）。",
    },
    {
        "question": "发酵对面包风味有什么影响？",
        "ground_truth": "酵母发酵产生乙醇、有机酸（乳酸、醋酸）、酯类等数百种挥发性化合物，同时长时间发酵有利于酶促水解产生氨基酸，与糖参与美拉德反应增加风味深度。",
    },
]


# ── Retrieval call ────────────────────────────────────────────────────────────

def call_retrieve(client: httpx.Client, question: str, top_k: int = 8) -> dict:
    resp = client.post(
        f"{RETRIEVAL_API_URL}/retrieve",
        json={"q": question, "top_k": top_k, "return_contexts": True,
              "generate_answer": True},
        timeout=LINGYA_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


# ── Lingya Gemini judge ───────────────────────────────────────────────────────

def _lingya_api_key() -> str:
    api_key = os.environ.get("L0_API_KEY") or L0_API_KEY
    if not api_key:
        raise RuntimeError("L0_API_KEY not set - required for RAGAS judge")
    return api_key


def _lingya_api_url() -> str:
    endpoint = os.environ.get("L0_API_ENDPOINT", "").rstrip("/")
    if endpoint:
        return f"{endpoint}/v1"
    if LINGYA_API_URL and LINGYA_API_URL != "/v1":
        return LINGYA_API_URL.rstrip("/")
    raise RuntimeError("L0_API_ENDPOINT not set - required for RAGAS judge")


def _post_lingya_judge(client: httpx.Client, prompt: str) -> httpx.Response:
    return post_lingya_chat(
        client,
        f"{_lingya_api_url()}/chat/completions",
        {
            "Authorization": f"Bearer {_lingya_api_key()}",
            "Content-Type": "application/json",
        },
        {
            "model": JUDGE_MODEL,
            "messages": [{
                "role": "user",
                "content": (
                    prompt
                    + "\n\nOnly respond with a number between 0 and 1 "
                    + "(e.g., 0.75). No explanation."
                ),
            }],
            "temperature": 0,
            "max_tokens": 16,
        },
        max_retries=LINGYA_MAX_RETRIES,
        timeout=LINGYA_TIMEOUT_SECONDS,
        backoff=LINGYA_BACKOFF_SECONDS,
    )

def llm_judge(client: httpx.Client, prompt: str) -> float:
    """Call Lingya Gemini to score on 0-1 scale. Returns float."""
    resp = _post_lingya_judge(client, prompt)
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    import re
    nums = re.findall(r"0?\.\d+|1\.0|^0$|^1$", text)
    return float(nums[0]) if nums else 0.5


def score_context_precision(client: httpx.Client, question: str,
                             contexts: list[dict], ground_truth: str) -> float:
    if not contexts:
        return 0.0
    scores = []
    for ctx in contexts:
        prompt = f"""Evaluate whether this retrieved context is relevant to answer the question.
Question: {question}
Context: {ctx['text'][:500]}
Relevant (0-1)?"""
        scores.append(llm_judge(client, prompt))
    return sum(scores) / len(scores)


def score_context_recall(client: httpx.Client, question: str,
                          contexts: list[dict], ground_truth: str) -> float:
    if not ground_truth or not contexts:
        return 0.0
    ctx_combined = " ".join(c["text"][:300] for c in contexts[:5])
    prompt = f"""Given the ground truth answer and the retrieved contexts, estimate what fraction of the ground truth information is present in the contexts.
Ground Truth: {ground_truth}
Contexts: {ctx_combined[:1500]}
Coverage score (0-1)?"""
    return llm_judge(client, prompt)


def score_faithfulness(client: httpx.Client, answer: str,
                        contexts: list[dict]) -> float:
    if not answer or not contexts:
        return 0.0
    ctx_combined = " ".join(c["text"][:300] for c in contexts[:5])
    prompt = f"""Evaluate whether the answer is fully supported by (faithful to) the provided contexts.
Answer: {answer[:500]}
Contexts: {ctx_combined[:1500]}
Faithfulness score (0-1, where 1 = fully supported)?"""
    return llm_judge(client, prompt)


def score_answer_relevancy(client: httpx.Client, question: str, answer: str) -> float:
    if not answer:
        return 0.0
    prompt = f"""Evaluate how relevant and complete this answer is for the given question.
Question: {question}
Answer: {answer[:500]}
Relevancy score (0-1)?"""
    return llm_judge(client, prompt)


# ── Main evaluation loop ──────────────────────────────────────────────────────

def run_evaluation(questions: list[dict], output_path: Path | None = None,
                   verbose: bool = True) -> dict:
    cfg = load_eval_config()
    judge_model_name = cfg.get("judge_model", JUDGE_MODEL)

    client = httpx.Client(trust_env=False, timeout=LINGYA_TIMEOUT_SECONDS)
    results = []
    t0 = time.time()

    if verbose:
        print(f"Judge model: {judge_model_name} (Lingya gemini-3.1-pro — independent of Claude answer gen)")

    for i, item in enumerate(questions):
        q = item["question"]
        gt = item.get("ground_truth", "")
        if verbose:
            print(f"\n[{i+1}/{len(questions)}] Q: {q[:60]}...")

        try:
            resp = call_retrieve(client, q)
        except Exception as e:
            print(f"  ERROR: retrieval failed: {e}")
            results.append({"question": q, "error": str(e)})
            continue

        answer   = resp.get("answer", "")
        contexts = resp.get("contexts", [])
        if verbose:
            print(f"  contexts: {len(contexts)}, latency: {resp.get('latency_ms')}ms")
            print(f"  answer: {answer[:80]}...")

        cp  = score_context_precision(client, q, contexts, gt)
        cr  = score_context_recall(client, q, contexts, gt)
        f   = score_faithfulness(client, answer, contexts)
        ar  = score_answer_relevancy(client, q, answer)

        result = {
            "question":           q,
            "answer":             answer,
            "context_count":      len(contexts),
            "context_precision":  round(cp, 3),
            "context_recall":     round(cr, 3),
            "faithfulness":       round(f, 3),
            "answer_relevancy":   round(ar, 3),
            "judge_model":        judge_model_name,
            "contexts":           [{"source": c["source"], "score": c["score"],
                                    "text": c["text"][:200]} for c in contexts[:3]],
        }
        results.append(result)
        if verbose:
            print(f"  CP={cp:.2f} CR={cr:.2f} F={f:.2f} AR={ar:.2f}")

    client.close()

    valid = [r for r in results if "error" not in r]
    if not valid:
        print("No valid results!")
        return {"error": "all failed"}

    agg = {
        "context_precision":  round(sum(r["context_precision"] for r in valid) / len(valid), 3),
        "context_recall":     round(sum(r["context_recall"]     for r in valid) / len(valid), 3),
        "faithfulness":       round(sum(r["faithfulness"]        for r in valid) / len(valid), 3),
        "answer_relevancy":   round(sum(r["answer_relevancy"]    for r in valid) / len(valid), 3),
        "judge_model":        judge_model_name,
        "n_questions":        len(valid),
        "elapsed_s":          round(time.time() - t0, 1),
        "per_question":       results,
    }

    print(f"\n{'='*50}")
    print(f"RAGAS Results ({len(valid)} questions, {agg['elapsed_s']}s)")
    print(f"  Judge: {judge_model_name}")
    print(f"  Context Precision:  {agg['context_precision']:.3f}")
    print(f"  Context Recall:     {agg['context_recall']:.3f}")
    print(f"  Faithfulness:       {agg['faithfulness']:.3f}")
    print(f"  Answer Relevancy:   {agg['answer_relevancy']:.3f}")
    print(f"{'='*50}")

    if output_path:
        output_path.write_text(json.dumps(agg, ensure_ascii=False, indent=2))
        print(f"Results saved to {output_path}")

    return agg


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="RAGAS evaluation for Y-system")
    parser.add_argument("input", nargs="?", default="dummy",
                        help="Input JSON file or 'dummy' for built-in test questions")
    parser.add_argument("--output", "-o", type=str, default=None)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if args.input == "dummy":
        questions = DUMMY_QUESTIONS
        print(f"Using {len(questions)} dummy questions")
    else:
        path = Path(args.input)
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)
        questions = json.loads(path.read_text())
        print(f"Loaded {len(questions)} questions from {path}")

    if args.limit:
        questions = questions[:args.limit]

    output_path = Path(args.output) if args.output else None
    run_evaluation(questions, output_path)


if __name__ == "__main__":
    main()
