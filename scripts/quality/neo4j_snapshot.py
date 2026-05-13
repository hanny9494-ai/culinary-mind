#!/usr/bin/env python3
"""P2-Rb1: Neo4j Snapshot + Rollback.

Modes:
- snapshot  — dump current DB to neo4j-admin export OR cypher-shell APOC export
- list      — list snapshots in /Users/jeff/culinary-mind/output/snapshots/
- rollback  — restore from snapshot

Strategy:
- Use APOC export.cypher.all (writes Cypher CREATE statements)
- Snapshots stored under output/snapshots/{tag}/all.cypher
- Snapshot meta in {tag}/meta.yaml: {created_at, node_count, edge_count, git_commit}
- Rollback: WIPES current DB then replays Cypher

Caveats:
- APOC must be installed. If not, fallback to manual JSON export.
- Rollback is destructive — requires --i-know-what-im-doing flag
"""
import sys
import time
import subprocess
import argparse
from pathlib import Path

import yaml
from neo4j import GraphDatabase

ROOT = Path("/Users/jeff/culinary-mind")
SNAP_DIR = ROOT / "output/snapshots"
SNAP_DIR.mkdir(parents=True, exist_ok=True)

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "cmind_p1_33_proto")


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()[:8]
    except Exception:
        return "unknown"


def stats(sess):
    n = sess.run("MATCH (n) RETURN count(n) AS n").single()["n"]
    e = sess.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
    return n, e


def snapshot(tag: str):
    out_dir = SNAP_DIR / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    d = GraphDatabase.driver(URI, auth=AUTH)
    t0 = time.time()
    with d.session() as s:
        n, e = stats(s)
        # Try APOC export
        try:
            cypher_file = out_dir / "all.cypher"
            # APOC writes to Neo4j import dir by default; use stream mode then save
            res = s.run(
                "CALL apoc.export.cypher.all(null, {format:'plain', stream:true}) "
                "YIELD cypherStatements RETURN cypherStatements"
            )
            with open(cypher_file, "w") as f:
                for r in res:
                    f.write(r["cypherStatements"])
            mode = "apoc_cypher"
        except Exception as ex:
            # Fallback: manual JSON
            json_file = out_dir / "nodes_edges.jsonl"
            import json
            with open(json_file, "w") as f:
                for r in s.run("MATCH (n) RETURN labels(n) AS l, properties(n) AS p, id(n) AS i"):
                    f.write(json.dumps({"kind": "node", "id": r["i"], "labels": r["l"], "props": r["p"]}, default=str) + "\n")
                for r in s.run("MATCH (s)-[r]->(t) RETURN id(s) AS s, id(t) AS t, type(r) AS rt, properties(r) AS p"):
                    f.write(json.dumps({"kind": "edge", "src_id": r["s"], "tgt_id": r["t"], "rel": r["rt"], "props": r["p"]}, default=str) + "\n")
            mode = f"fallback_jsonl ({ex.__class__.__name__})"

    meta = {
        "tag": tag,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "node_count": n,
        "edge_count": e,
        "git_commit": git_commit(),
        "mode": mode,
        "elapsed_s": round(time.time() - t0, 2),
    }
    (out_dir / "meta.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    print(f"✅ Snapshot '{tag}' created in {out_dir}")
    print(yaml.safe_dump(meta, sort_keys=False))


def list_snapshots():
    snaps = sorted(SNAP_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for s in snaps:
        meta_f = s / "meta.yaml"
        if meta_f.exists():
            m = yaml.safe_load(meta_f.read_text())
            print(f"{s.name:<30} {m.get('created_at')} nodes={m.get('node_count')} edges={m.get('edge_count')} commit={m.get('git_commit')}")


def rollback(tag: str, confirm: bool):
    if not confirm:
        print("Refusing to rollback without --i-know-what-im-doing")
        sys.exit(1)
    out_dir = SNAP_DIR / tag
    if not out_dir.exists():
        print(f"Snapshot not found: {out_dir}")
        sys.exit(1)
    cypher_file = out_dir / "all.cypher"
    if not cypher_file.exists():
        print(f"Cypher file missing — APOC-mode snapshot required for rollback: {cypher_file}")
        sys.exit(1)

    d = GraphDatabase.driver(URI, auth=AUTH)
    print(f"WIPING current Neo4j DB and replaying {cypher_file}")
    with d.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
        # Replay in batches (cypher file may be large)
        with open(cypher_file) as f:
            stmt_buf = ""
            for line in f:
                stmt_buf += line
                if line.strip().endswith(";"):
                    try:
                        s.run(stmt_buf)
                    except Exception as ex:
                        print(f"WARN: {ex} on stmt: {stmt_buf[:200]}")
                    stmt_buf = ""
    print(f"✅ Rollback to '{tag}' complete")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_snap = sub.add_parser("snapshot"); p_snap.add_argument("--tag", required=True)
    sub.add_parser("list")
    p_back = sub.add_parser("rollback"); p_back.add_argument("--tag", required=True); p_back.add_argument("--i-know-what-im-doing", action="store_true", dest="confirm")
    args = ap.parse_args()
    if args.cmd == "snapshot":
        snapshot(args.tag)
    elif args.cmd == "list":
        list_snapshots()
    elif args.cmd == "rollback":
        rollback(args.tag, args.confirm)

if __name__ == "__main__":
    main()
