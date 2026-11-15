#!/usr/bin/env python3
"""G4 replay job: --input exported-proposals.json, or read the local Neo4j log."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

from _common.effect_replay import validate_replay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.input:
        documents = json.loads(args.input.read_text(encoding="utf-8"))
        source = str(args.input)
    else:
        from neo4j import GraphDatabase

        with GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                                  auth=(os.getenv("NEO4J_USER", "neo4j"),
                                        os.getenv("NEO4J_PASSWORD", "art-digital-twin"))) as driver:
            with driver.session() as session:
                documents = [json.loads(row["document"]) for row in session.run(
                    "MATCH (p:ActionProposal) RETURN p.document AS document")]
        source = "Neo4j ActionProposal log"
    if not isinstance(documents, list):
        parser.error("input must be a JSON array of proposal documents")
    report = {"source": source, "documents": len(documents), **validate_replay(documents)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return int(any(v["status"] == "failed" for v in report["by_action_type"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
