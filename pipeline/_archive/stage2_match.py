#!/usr/bin/env python3
"""
Stage 2 — 题目-Chunk 语义匹配
306题母表 × chunks_smart.json → Gemini Embedding cosine匹配 → question_chunk_matches.json

用法:
  python3 scripts/stage2_match.py \
    --chunks output/mc/vol2/stage1/chunks_smart.json \
    --chunks output/mc/vol3/stage1/chunks_smart.json \
    --questions data/l0_question_master.json \
    --output output/stage2/question_chunk_matches.json \
    --config config/api.yaml \
    --top-k 3 \
    --threshold 0.70 \
    --dry-run
"""

import argparse
import json
import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np
import requests
import yaml


# ── 默认值 ────────────────────────────────────────────────────────────────────
DEFAULT_TOP_K = 3
DEFAULT_THRESHOLD = 0.70
GEMINI_BATCH_SIZE = 20        # 小批次避免429
GEMINI_BATCH_DELAY = 6.0      # 批次间延迟（秒）
MAX_RETRIES = 5
RETRY_BACKOFF = 3.0           # 指数退避基数


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_questions(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return []
        data = json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ 无法解析题目文件 {path}: {e}", file=sys.stderr)
        return []
    # 支持 list 或 {"questions": [...]}
    if isinstance(data, dict):
        data = data.get("questions", [])
    return data


def load_chunks(paths: list[str]) -> list[dict]:
    """加载一个或多个 chunks_smart.json，合并后返回统一格式的 chunk 列表。"""
    all_chunks = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                print(f"⚠️ 空文件: {p}，跳过", file=sys.stderr)
                continue
            data = json.loads(content)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ 无法解析 chunks 文件 {p}: {e}，跳过", file=sys.stderr)
            continue

        # OFC 格式: {"chunks": [...]}
        if isinstance(data, dict) and "chunks" in data:
            raw = data["chunks"]
            source_book = data.get("source_book", "")
        # MC 格式: [...]
        elif isinstance(data, list):
            raw = data
            source_book = ""
        else:
            print(f"⚠️ 未知 chunks 格式: {p}，跳过", file=sys.stderr)
            continue

        for chunk in raw:
            sb = chunk.get("source_book", source_book)
            idx = chunk.get("chunk_idx", chunk.get("idx", 0))

            # chunk_id: 多书合并时带 source_book 前缀
            if sb:
                chunk_id = f"{sb}:chunk_{idx}"
            else:
                chunk_id = f"chunk_{idx}"

            all_chunks.append({
                "chunk_id": chunk_id,
                "chunk_idx": idx,
                "source_book": sb,
                "chapter": chunk.get("chapter", None),
                "chapter_title": chunk.get("chapter_title", ""),
                "summary": chunk.get("summary", ""),
                "full_text": chunk.get("full_text", ""),
                "topics": chunk.get("topics", []),
            })

    return all_chunks


def build_chunk_text(chunk: dict) -> str:
    """构建用于 embedding 的文本：summary优先 + full_text前500字。"""
    summary = (chunk.get("summary") or "").strip()
    full_text = (chunk.get("full_text") or "").strip()[:500]
    if summary and full_text:
        return summary + " " + full_text
    return summary or full_text


# ── Embedding 缓存 ───────────────────────────────────────────────────────────

def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_cache(cache_path: str) -> dict:
    p = Path(cache_path)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict, cache_path: str):
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# ── Lingya Gemini Embedding API ──────────────────────────────────────────────

def gemini_embed_batch(texts: list[str], api_key: str, model: str) -> list[list[float]]:
    """调用灵雅 OpenAI-compatible embeddings，一次最多100条。"""
    endpoint = os.environ.get("L0_API_ENDPOINT", "").rstrip("/")
    if not endpoint:
        raise RuntimeError("L0_API_ENDPOINT 未设置")
    url = f"{endpoint}/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "input": [t[:8000] for t in texts]}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=600)
            resp.raise_for_status()
            embeddings = resp.json()["data"]
            return [e["embedding"] for e in embeddings]
        except (requests.RequestException, KeyError) as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                print(f"  Lingya Gemini API 重试 {attempt}/{MAX_RETRIES}，等待 {wait:.0f}s: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Lingya Gemini API 调用失败 ({MAX_RETRIES}次重试后): {e}")


# ── Ollama Embedding API ─────────────────────────────────────────────────────

def _ollama_session(base_url: str) -> requests.Session:
    """创建绕过代理的 Ollama session。"""
    s = requests.Session()
    s.trust_env = False  # 忽略 http_proxy / https_proxy
    return s


def ollama_embed_batch(texts: list[str], base_url: str, model: str) -> list[list[float]]:
    """调用 Ollama embedding API，批量请求。"""
    session = _ollama_session(base_url)
    # Ollama /api/embed 支持 input 为 list
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(
                f"{base_url}/api/embed",
                json={"model": model, "input": texts},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["embeddings"]
        except (requests.RequestException, KeyError) as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF ** attempt)
            else:
                raise RuntimeError(f"Ollama API 失败: {e}")
    return []


# ── 统一 Embedding 接口 ──────────────────────────────────────────────────────

def embed_texts(
    texts: list[str],
    cache: dict,
    use_ollama: bool,
    config: dict,
    cache_path: str = "",
) -> np.ndarray:
    """对一组文本进行 embedding 编码，使用缓存避免重复调用。返回 (N, dim) 的 numpy 矩阵。"""

    # 找出哪些需要编码
    hashes = [text_hash(t) for t in texts]
    uncached_indices = [i for i, h in enumerate(hashes) if h not in cache]

    if uncached_indices:
        uncached_texts = [texts[i] for i in uncached_indices]
        print(f"  需要编码 {len(uncached_texts)} 条（缓存命中 {len(texts) - len(uncached_texts)} 条）")

        emb_idx = 0  # 跟踪已完成的 embedding 数
        if use_ollama:
            ollama_cfg = config.get("ollama", {})
            base_url = ollama_cfg.get("url", "http://localhost:11434")
            model = ollama_cfg.get("models", {}).get("embedding", "qwen3-embedding:8b")
            batch_size = 50
            for start in range(0, len(uncached_texts), batch_size):
                batch = uncached_texts[start:start + batch_size]
                embs = ollama_embed_batch(batch, base_url, model)
                for j, emb in enumerate(embs):
                    cache[hashes[uncached_indices[emb_idx + j]]] = emb
                emb_idx += len(embs)
                print(f"    Ollama: {emb_idx}/{len(uncached_texts)}")
        else:
            gemini_cfg = config.get("gemini", {})
            api_key = os.environ.get("L0_API_KEY") or gemini_cfg.get("api_key", "")
            if api_key.startswith("${") and api_key.endswith("}"):
                api_key = os.environ.get(api_key[2:-1], "")
            model = gemini_cfg.get("embedding_model") or gemini_cfg.get("model", "gemini-embedding-001")

            if not api_key:
                print("❌ L0_API_KEY 未设置", file=sys.stderr)
                sys.exit(1)

            for start in range(0, len(uncached_texts), GEMINI_BATCH_SIZE):
                batch = uncached_texts[start:start + GEMINI_BATCH_SIZE]
                embs = gemini_embed_batch(batch, api_key, model)
                for j, emb in enumerate(embs):
                    cache[hashes[uncached_indices[emb_idx + j]]] = emb
                emb_idx += len(embs)
                print(f"    Gemini: {emb_idx}/{len(uncached_texts)}")
                # 每批次后保存缓存（防崩溃丢失）
                if cache_path:
                    save_cache(cache, cache_path)
                # 限速：批次间延迟
                if emb_idx < len(uncached_texts):
                    time.sleep(GEMINI_BATCH_DELAY)
    else:
        print(f"  全部缓存命中（{len(texts)} 条）")

    # 组装结果矩阵
    vectors = [cache[h] for h in hashes]
    return np.array(vectors, dtype=np.float32)


# ── Cosine 匹配（矩阵化） ────────────────────────────────────────────────────

def cosine_similarity_matrix(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """计算 A(M,d) 与 B(N,d) 之间的 cosine similarity 矩阵 (M,N)。"""
    # 归一化
    A_norm = A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-10)
    B_norm = B / (np.linalg.norm(B, axis=1, keepdims=True) + 1e-10)
    return A_norm @ B_norm.T


def match_questions_to_chunks(
    sim_matrix: np.ndarray,
    questions: list[dict],
    chunks: list[dict],
    top_k: int,
    threshold: float,
) -> list[dict]:
    """根据 cosine 相似度矩阵，为每题取 top-k chunks。"""
    results = []
    for qi in range(len(questions)):
        q = questions[qi]
        scores = sim_matrix[qi]
        top_indices = np.argsort(scores)[::-1][:top_k]

        top_chunks = []
        for ci in top_indices:
            score = float(scores[ci])
            if score < threshold:
                continue
            c = chunks[ci]
            top_chunks.append({
                "chunk_id": c["chunk_id"],
                "score": round(score, 4),
                "chapter": c.get("chapter"),
                "chapter_title": c.get("chapter_title", ""),
                "source_book": c.get("source_book", ""),
                "preview": (c.get("full_text") or "")[:200],
            })

        match_status = "matched" if top_chunks else "unmatched"
        results.append({
            "question_id": q.get("question_id", ""),
            "question_text": q.get("question_text", ""),
            "domain": q.get("domain", ""),
            "top_chunks": top_chunks,
            "match_status": match_status,
        })

    return results


# ── 质量报告 ──────────────────────────────────────────────────────────────────

def generate_report(results: list[dict]) -> dict:
    matched = [r for r in results if r["match_status"] == "matched"]
    unmatched = [r for r in results if r["match_status"] == "unmatched"]

    # top1 / top3 平均分
    top1_scores = []
    all_scores = []
    for r in matched:
        chunks = r["top_chunks"]
        if chunks:
            top1_scores.append(chunks[0]["score"])
            all_scores.extend(c["score"] for c in chunks)

    # domain覆盖率
    domain_stats = {}
    for r in results:
        d = r.get("domain", "unknown")
        if d not in domain_stats:
            domain_stats[d] = {"matched": 0, "total": 0, "scores": []}
        domain_stats[d]["total"] += 1
        if r["match_status"] == "matched":
            domain_stats[d]["matched"] += 1
            for c in r["top_chunks"]:
                domain_stats[d]["scores"].append(c["score"])

    domain_coverage = {}
    for d, s in sorted(domain_stats.items()):
        domain_coverage[d] = {
            "matched": s["matched"],
            "total": s["total"],
            "avg_score": round(np.mean(s["scores"]), 4) if s["scores"] else 0,
        }

    report = {
        "total_questions": len(results),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "match_rate": round(len(matched) / max(len(results), 1), 4),
        "avg_top1_score": round(np.mean(top1_scores), 4) if top1_scores else 0,
        "avg_top3_score": round(np.mean(all_scores), 4) if all_scores else 0,
        "domain_coverage": domain_coverage,
        "unmatched_questions": [r["question_id"] for r in unmatched],
    }
    return report


def print_report(report: dict):
    print("\n" + "=" * 60)
    print("Stage 2 匹配报告")
    print("=" * 60)
    print(f"  题目总数:     {report['total_questions']}")
    print(f"  已匹配:       {report['matched']}")
    print(f"  未匹配:       {report['unmatched']}")
    print(f"  匹配率:       {report['match_rate']:.1%}")
    print(f"  avg top1:     {report['avg_top1_score']:.4f}")
    print(f"  avg top3:     {report['avg_top3_score']:.4f}")
    print()
    print("  Domain覆盖:")
    for d, s in report["domain_coverage"].items():
        print(f"    {d:<30} {s['matched']:>3}/{s['total']:<3}  avg={s['avg_score']:.4f}")
    if report["unmatched_questions"]:
        print()
        print(f"  未匹配题目 ({len(report['unmatched_questions'])}条):")
        for qid in report["unmatched_questions"]:
            print(f"    {qid}")
    print("=" * 60)


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Stage 2 — 题目-Chunk 语义匹配",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # dry-run（不调用 embedding API）
  python3 scripts/stage2_match.py \\
    --chunks output/mc/vol2/stage1/chunks_smart.json \\
    --questions data/l0_question_master.json \\
    --output /tmp/test.json --dry-run

  # 实际运行（Gemini embedding）
  python3 scripts/stage2_match.py \\
    --chunks output/mc/vol2/stage1/chunks_smart.json \\
    --chunks output/mc/vol3/stage1/chunks_smart.json \\
    --questions data/l0_question_master.json \\
    --output output/stage2/question_chunk_matches.json

  # 使用 Ollama 本地模型
  python3 scripts/stage2_match.py \\
    --chunks output/mc/vol2/stage1/chunks_smart.json \\
    --questions data/l0_question_master.json \\
    --output output/stage2/question_chunk_matches.json \\
    --use-ollama
        """,
    )
    parser.add_argument(
        "--chunks", action="append", required=True,
        help="chunks_smart.json 路径（可多次指定合并多书）",
    )
    parser.add_argument("--questions", required=True, help="l0_question_master.json 路径")
    parser.add_argument("--output", required=True, help="输出 question_chunk_matches.json 路径")
    parser.add_argument("--config", default="config/api.yaml", help="API 配置文件")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help=f"每题取 top-k chunks（默认 {DEFAULT_TOP_K}）")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help=f"cosine 相似度阈值（默认 {DEFAULT_THRESHOLD}）")
    parser.add_argument("--use-ollama", action="store_true", help="使用 Ollama 本地 embedding 而不是 Gemini")
    parser.add_argument("--dry-run", action="store_true", help="只加载数据打印统计，不调用 embedding API")
    parser.add_argument("--cache-dir", default=None, help="embedding 缓存目录（默认与 output 同目录）")
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 加载数据
    print("加载数据...")
    questions = load_questions(args.questions)
    print(f"  题目: {len(questions)} 条")

    chunks = load_chunks(args.chunks)
    print(f"  Chunks: {len(chunks)} 条（来自 {len(args.chunks)} 个文件）")

    if not questions or not chunks:
        print("⚠️ 题目或 chunks 为空，生成空输出")
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return

    # 构建文本
    q_texts = [q.get("question_text", "") for q in questions]
    c_texts = [build_chunk_text(c) for c in chunks]
    print(f"  Question 文本平均长度: {np.mean([len(t) for t in q_texts]):.0f} 字符")
    print(f"  Chunk 文本平均长度:    {np.mean([len(t) for t in c_texts]):.0f} 字符")

    # Source book统计
    books = {}
    for c in chunks:
        sb = c.get("source_book", "unknown")
        books[sb] = books.get(sb, 0) + 1
    for sb, cnt in sorted(books.items()):
        print(f"  {sb}: {cnt} chunks")

    if args.dry_run:
        print("\n[dry-run] 跳过 embedding 编码和匹配")
        print(f"  如果正式运行，将编码 {len(q_texts)} 条题目 + {len(c_texts)} 条 chunks")
        provider = "Ollama" if args.use_ollama else "Gemini"
        print(f"  Embedding 提供方: {provider}")
        if not args.use_ollama:
            batches = (len(q_texts) + len(c_texts) + GEMINI_BATCH_SIZE - 1) // GEMINI_BATCH_SIZE
            print(f"  Gemini API 批次: ~{batches} 次")
        return

    # 缓存路径
    cache_dir = args.cache_dir or str(Path(args.output).parent)
    cache_path = os.path.join(cache_dir, "embeddings_cache.json")
    cache = load_cache(cache_path)
    print(f"  Embedding 缓存: {len(cache)} 条已有")

    # Embedding 编码
    print("\n编码题目...")
    q_matrix = embed_texts(q_texts, cache, args.use_ollama, config, cache_path)

    print("\n编码 chunks...")
    c_matrix = embed_texts(c_texts, cache, args.use_ollama, config, cache_path)

    # 最终保存缓存
    save_cache(cache, cache_path)
    print(f"\n缓存已保存: {cache_path}（{len(cache)} 条）")

    # Cosine 匹配
    print(f"\n计算 cosine 相似度矩阵 ({len(questions)}×{len(chunks)})...")
    sim_matrix = cosine_similarity_matrix(q_matrix, c_matrix)

    results = match_questions_to_chunks(
        sim_matrix, questions, chunks, args.top_k, args.threshold,
    )

    # 保存结果
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n匹配结果已保存: {args.output}")

    # 质量报告
    report = generate_report(results)
    report_path = os.path.join(str(Path(args.output).parent), "match_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告已保存: {report_path}")

    print_report(report)


if __name__ == "__main__":
    main()
