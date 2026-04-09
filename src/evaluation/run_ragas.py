"""Y-S1-3: RAGAS evaluation scaffold for the Y-system retrieval API.

Adapted from LightRAG evaluation/ pattern.
Runs 4 RAGAS metrics: Context Precision, Context Recall, Faithfulness, Answer Relevancy.

Usage:
  # Dummy test (5 questions, no real API needed):
  python -m src.evaluation.run_ragas dummy

  # Real evaluation:
  python -m src.evaluation.run_ragas eval_set.json --output results.json

  # Golden set:
  python -m src.evaluation.run_ragas data/golden_set/golden_v0.json

Input JSON format:
  [
    {
      "question": "为什么烤鸡胸柴？",
      "ground_truth": "鸡胸肌肉纤维细，..."   (optional, needed for recall/faithfulness)
    },
    ...
  ]

Output:
  {
    "context_precision":    0.xx,
    "context_recall":       0.xx,
    "faithfulness":         0.xx,
    "answer_relevancy":     0.xx,
    "per_question": [...]
  }
"""
from __future__ import annotations

import asyncio
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

RETRIEVAL_API_URL = os.getenv("RETRIEVAL_API_URL", "http://localhost:8760")
OLLAMA_URL        = os.getenv("OLLAMA_URL", "http://localhost:11434")
JUDGE_MODEL       = os.getenv("JUDGE_MODEL", "qwen3.5:9b")

REPO_ROOT = Path(__file__).resolve().parents[2]


# ─── Dummy data ─────────────────────────────────────────────────────────────────

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


# ─── Retrieval call ─────────────────────────────────────────────────────────────

def call_retrieve(client: httpx.Client, question: str, top_k: int = 8) -> dict:
    """Call the retrieval API and return raw response."""
    resp = client.post(
        f"{RETRIEVAL_API_URL}/retrieve",
        json={"q": question, "top_k": top_k, "return_contexts": True,
              "generate_answer": True},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


# ─── RAGAS-style scoring (local, no OpenAI required) ────────────────────────────

def llm_judge(client: httpx.Client, prompt: str) -> float:
    """Call local LLM to score on 0-1 scale. Returns float."""
    resp = client.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": JUDGE_MODEL,
            "prompt": "/no_think\n" + prompt + "\n\nOnly respond with a number between 0 and 1 (e.g., 0.75). No explanation.",
            "stream": False,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 16},
        },
        timeout=90,
    )
    resp.raise_for_status()
    text = resp.json()["response"].strip()
    # Parse first float found
    import re
    nums = re.findall(r"0?\.\d+|1\.0|0|1", text)
    return float(nums[0]) if nums else 0.5


def score_context_precision(client: httpx.Client, question: str,
                             contexts: list[dict], ground_truth: str) -> float:
    """Context Precision: fraction of retrieved contexts that are relevant."""
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
    """Context Recall: how much of the ground truth is covered by retrieved contexts."""
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
    """Faithfulness: fraction of answer claims supported by contexts."""
    if not answer or not contexts:
        return 0.0
    ctx_combined = " ".join(c["text"][:300] for c in contexts[:5])
    prompt = f"""Evaluate whether the answer is fully supported by (faithful to) the provided contexts.
Answer: {answer[:500]}
Contexts: {ctx_combined[:1500]}
Faithfulness score (0-1, where 1 = fully supported)?"""
    return llm_judge(client, prompt)


def score_answer_relevancy(client: httpx.Client, question: str, answer: str) -> float:
    """Answer Relevancy: how well the answer addresses the question."""
    if not answer:
        return 0.0
    prompt = f"""Evaluate how relevant and complete this answer is for the given question.
Question: {question}
Answer: {answer[:500]}
Relevancy score (0-1)?"""
    return llm_judge(client, prompt)


# ─── Main evaluation loop ────────────────────────────────────────────────────────

def run_evaluation(questions: list[dict], output_path: Path | None = None,
                   verbose: bool = True) -> dict:
    client = httpx.Client(trust_env=False, timeout=120)
    results = []
    t0 = time.time()

    for i, item in enumerate(questions):
        q = item["question"]
        gt = item.get("ground_truth", "")
        if verbose:
            print(f"\n[{i+1}/{len(questions)}] Q: {q[:60]}...")

        # 1. Retrieve
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

        # 2. Score
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
            "contexts":           [{"source": c["source"], "score": c["score"],
                                    "text": c["text"][:200]} for c in contexts[:3]],
        }
        results.append(result)
        if verbose:
            print(f"  CP={cp:.2f} CR={cr:.2f} F={f:.2f} AR={ar:.2f}")

    client.close()

    # Aggregate
    valid = [r for r in results if "error" not in r]
    if not valid:
        print("No valid results!")
        return {"error": "all failed"}

    agg = {
        "context_precision":  round(sum(r["context_precision"] for r in valid) / len(valid), 3),
        "context_recall":     round(sum(r["context_recall"]     for r in valid) / len(valid), 3),
        "faithfulness":       round(sum(r["faithfulness"]        for r in valid) / len(valid), 3),
        "answer_relevancy":   round(sum(r["answer_relevancy"]    for r in valid) / len(valid), 3),
        "n_questions":        len(valid),
        "elapsed_s":          round(time.time() - t0, 1),
        "per_question":       results,
    }

    print(f"\n{'='*50}")
    print(f"RAGAS Results ({len(valid)} questions, {agg['elapsed_s']}s)")
    print(f"  Context Precision:  {agg['context_precision']:.3f}")
    print(f"  Context Recall:     {agg['context_recall']:.3f}")
    print(f"  Faithfulness:       {agg['faithfulness']:.3f}")
    print(f"  Answer Relevancy:   {agg['answer_relevancy']:.3f}")
    print(f"{'='*50}")

    if output_path:
        output_path.write_text(json.dumps(agg, ensure_ascii=False, indent=2))
        print(f"Results saved to {output_path}")

    return agg


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="RAGAS evaluation for Y-system")
    parser.add_argument("input", nargs="?", default="dummy",
                        help="Input JSON file or 'dummy' for built-in test questions")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output JSON file for results")
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
