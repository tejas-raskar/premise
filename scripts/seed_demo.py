"""Seed measured r1 evidence for the deterministic tool-client demonstration."""

import argparse
import json
import os
from pathlib import Path

from premise.demo import create_demo
from premise.memory import Memory
from premise.repository import Repository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path(os.environ.get("PREMISE_DEMO_REPO", ".artifacts/demo-repo")),
    )
    args = parser.parse_args()
    project = create_demo(args.repository)
    memory = Memory(
        [project],
        host=os.environ.get("PREMISE_FALKOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("PREMISE_FALKOR_PORT", "6387")),
        graph_prefix=os.environ.get("PREMISE_GRAPH_PREFIX", "premise"),
    )
    revision = Repository(project.repository).resolve("r1")
    for kind in ("keyed", "unkeyed"):
        record = memory.record_decision(
            {
                "project": project.id,
                "request_id": f"seed-v1-{kind}-record",
                "revision": revision,
                "statement": f"Do not retry {kind} job requests. Retries create duplicate jobs.",
                "scope": f"{kind}-job-requests",
                "sources": [{"uri": f"git:{revision}:job_api.py", "note": "Observed retry risk"}],
                "supports": [[{"contract": f"{kind}-duplicates", "expected": True}]],
            }
        )
        result = memory.run_check(
            {
                "project": project.id,
                "request_id": f"seed-v1-{kind}-check",
                "revision": revision,
                "contract": f"{kind}-duplicates",
            }
        )
        print(
            json.dumps(
                {
                    "scope": f"{kind}-job-requests",
                    "decision_id": record["decision"]["id"],
                    "revision": revision,
                    "outcome": result["outcome"],
                }
            )
        )
        if result["outcome"] != "true":
            raise RuntimeError(f"Expected observed duplicates at r1 for {kind} requests")


if __name__ == "__main__":
    main()
