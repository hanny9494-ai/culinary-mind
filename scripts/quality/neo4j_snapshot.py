#!/usr/bin/env python3
"""P2-Rb1: Neo4j Snapshot + Rollback (Codex-6th hardened).

Fixes:
- P0: Atomic snapshot write (temp file → fsync → rename, complete flag in meta)
- P0: Fail-fast rollback (abort on first replay error, verify counts match snapshot meta)
- P2: URI/auth loaded from CMIND_NEO4J_* env vars (fallback to dev defaults)

Modes:
- snapshot  — dump current DB via APOC export.cypher.all
- list      — list snapshots
- rollback  — restore from snapshot (destructive; --i-know-what-im-doing required)
"""
import sys
import os
import time
import hashlib
import subprocess
import argparse
from pathlib import Path

import yaml
from neo4j import GraphDatabase

ROOT = Path("/Users/jeff/culinary-mind")
SNAP_DIR = ROOT / "output/snapshots"
SNAP_DIR.mkdir(parents=True, exist_ok=True)


def get_driver(env: str = "dev"):
    """Resolve URI + auth from env vars per docs/ops/staging_environment.md."""
    env_u = env.upper()
    uri = os.environ.get(f"CMIND_NEO4J_{env_u}_URI", "bolt://localhost:7687")
    user = os.environ.get(f"CMIND_NEO4J_{env_u}_USER", "neo4j")
    pw = os.environ.get(f"CMIND_NEO4J_{env_u}_PW", "cmind_p1_33_proto")
    if env != "dev" and not os.environ.get(f"CMIND_NEO4J_{env_u}_PW"):
        print(f"REFUSING: CMIND_NEO4J_{env_u}_PW must be set explicitly for non-dev env", file=sys.stderr)
        sys.exit(2)
    return GraphDatabase.driver(uri, auth=(user, pw)), uri


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()[:8]
    except Exception:
        return "unknown"


def stats(sess):
    n = sess.run("MATCH (n) RETURN count(n) AS n").single()["n"]
    e = sess.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
    return n, e


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(tag: str, env: str = "dev"):
    out_dir = SNAP_DIR / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    cypher_final = out_dir / "all.cypher"
    cypher_tmp = out_dir / f"all.cypher.tmp.{os.getpid()}"
    meta_path = out_dir / "meta.yaml"
    if cypher_final.exists():
        print(f"REFUSING: snapshot '{tag}' already exists. Pick a new tag.", file=sys.stderr)
        sys.exit(3)

    driver, uri = get_driver(env)
    t0 = time.time()
    mode = None
    n = e = 0
    try:
        with driver.session() as s:
            n, e = stats(s)
            try:
                res = s.run(
                    "CALL apoc.export.cypher.all(null, {format:'plain', stream:true}) "
                    "YIELD cypherStatements RETURN cypherStatements"
                )
                with open(cypher_tmp, "w") as f:
                    for r in res:
                        f.write(r["cypherStatements"])
                    f.flush()
                    os.fsync(f.fileno())
                mode = "apoc_cypher"
            except Exception as ex:
                # Cleanup partial cypher file if APOC failed
                if cypher_tmp.exists():
                    cypher_tmp.unlink()
                # Fallback: manual JSONL
                import json
                json_tmp = out_dir / f"nodes_edges.jsonl.tmp.{os.getpid()}"
                json_final = out_dir / "nodes_edges.jsonl"
                with open(json_tmp, "w") as f:
                    for r in s.run("MATCH (n) RETURN labels(n) AS l, properties(n) AS p, id(n) AS i"):
                        f.write(__import__("json").dumps({"kind": "node", "id": r["i"], "labels": r["l"], "props": r["p"]}, default=str) + "\n")
                    for r in s.run("MATCH (s)-[r]->(t) RETURN id(s) AS s, id(t) AS t, type(r) AS rt, properties(r) AS p"):
                        f.write(__import__("json").dumps({"kind": "edge", "src_id": r["s"], "tgt_id": r["t"], "rel": r["rt"], "props": r["p"]}, default=str) + "\n")
                    f.flush(); os.fsync(f.fileno())
                json_tmp.rename(json_final)
                mode = f"fallback_jsonl ({ex.__class__.__name__})"
    except Exception as ex:
        if cypher_tmp.exists(): cypher_tmp.unlink()
        raise

    # Atomic finalize: rename tmp → final ONLY if write completed
    if mode == "apoc_cypher":
        cypher_tmp.rename(cypher_final)

    meta = {
        "tag": tag,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "node_count": n,
        "edge_count": e,
        "git_commit": git_commit(),
        "uri": uri,
        "env": env,
        "mode": mode,
        "complete": True,  # Only written if we reach here
        "elapsed_s": round(time.time() - t0, 2),
    }
    if mode == "apoc_cypher":
        meta["sha256"] = sha256_of(cypher_final)
        meta["bytes"] = cypher_final.stat().st_size

    # Atomic meta write
    meta_tmp = meta_path.with_suffix(".tmp")
    meta_tmp.write_text(yaml.safe_dump(meta, sort_keys=False))
    meta_tmp.rename(meta_path)

    print(f"✅ Snapshot '{tag}' created in {out_dir}")
    print(yaml.safe_dump(meta, sort_keys=False))


def list_snapshots():
    snaps = sorted([p for p in SNAP_DIR.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    for sd in snaps:
        meta_f = sd / "meta.yaml"
        if meta_f.exists():
            m = yaml.safe_load(meta_f.read_text())
            complete = m.get("complete", False)
            mark = "✓" if complete else "✗ INCOMPLETE"
            print(f"{mark} {sd.name:<30} {m.get('created_at')} nodes={m.get('node_count')} edges={m.get('edge_count')} mode={m.get('mode')} commit={m.get('git_commit')}")
        else:
            print(f"✗ NO-META {sd.name}")


def rollback(tag: str, confirm: bool, env: str = "dev"):
    if not confirm:
        print("Refusing to rollback without --i-know-what-im-doing", file=sys.stderr)
        sys.exit(1)

    out_dir = SNAP_DIR / tag
    if not out_dir.exists():
        print(f"Snapshot not found: {out_dir}", file=sys.stderr); sys.exit(1)

    meta_path = out_dir / "meta.yaml"
    if not meta_path.exists():
        print(f"REFUSING: no meta.yaml — snapshot integrity unknown", file=sys.stderr); sys.exit(1)
    meta = yaml.safe_load(meta_path.read_text())
    if not meta.get("complete"):
        print(f"REFUSING: meta.complete is False — snapshot incomplete", file=sys.stderr); sys.exit(1)
    if meta.get("mode") != "apoc_cypher":
        print(f"REFUSING: snapshot mode={meta.get('mode')}; rollback supports apoc_cypher only", file=sys.stderr); sys.exit(1)

    cypher_file = out_dir / "all.cypher"
    if not cypher_file.exists():
        print(f"REFUSING: all.cypher missing", file=sys.stderr); sys.exit(1)

    # Verify checksum
    expected_sha = meta.get("sha256")
    if expected_sha:
        actual_sha = sha256_of(cypher_file)
        if actual_sha != expected_sha:
            print(f"REFUSING: checksum mismatch (expected {expected_sha[:12]}, got {actual_sha[:12]})", file=sys.stderr)
            sys.exit(1)

    driver, uri = get_driver(env)
    expected_n = meta.get("node_count")
    expected_e = meta.get("edge_count")
    print(f"WIPING {uri} and replaying {cypher_file} (expect nodes={expected_n}, edges={expected_e})")

    errors = []
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
        with open(cypher_file) as f:
            stmt_buf = ""
            for line in f:
                stmt_buf += line
                if line.strip().endswith(";"):
                    try:
                        s.run(stmt_buf)
                    except Exception as ex:
                        errors.append((str(ex), stmt_buf[:200]))
                        # Fail-fast: abort on first error
                        break
                    stmt_buf = ""

        if errors:
            print(f"❌ Rollback FAILED: {len(errors)} replay error(s). DB is partially restored.", file=sys.stderr)
            for err, snippet in errors[:3]:
                print(f"  - {err}\n    stmt: {snippet}", file=sys.stderr)
            sys.exit(2)

        # Verify counts match
        actual_n, actual_e = stats(s)
        if actual_n != expected_n or actual_e != expected_e:
            print(f"❌ Rollback count mismatch: got nodes={actual_n}/expected {expected_n}, edges={actual_e}/expected {expected_e}", file=sys.stderr)
            sys.exit(2)

    print(f"✅ Rollback to '{tag}' complete; verified {actual_n} nodes / {actual_e} edges")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev", choices=["dev", "staging", "prod"])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_snap = sub.add_parser("snapshot"); p_snap.add_argument("--tag", required=True)
    sub.add_parser("list")
    p_back = sub.add_parser("rollback")
    p_back.add_argument("--tag", required=True)
    p_back.add_argument("--i-know-what-im-doing", action="store_true", dest="confirm")
    args = ap.parse_args()
    if args.cmd == "snapshot":
        snapshot(args.tag, args.env)
    elif args.cmd == "list":
        list_snapshots()
    elif args.cmd == "rollback":
        rollback(args.tag, args.confirm, args.env)


if __name__ == "__main__":
    main()
