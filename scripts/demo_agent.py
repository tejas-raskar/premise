"""Run a deterministic MCP tool-client demo. The coding agent supplies reasoning."""

import argparse
import asyncio
import json

from mcp import Client


async def demonstrate(url: str) -> None:
    async with Client(url) as client:
        listing = await client.list_tools()
        names = sorted(tool.name for tool in listing.tools)
        expected = sorted(
            [
                "record_decision",
                "recall",
                "assess_changes",
                "run_check",
                "propose_replacement",
            ]
        )
        if names != expected:
            raise RuntimeError(f"Unexpected MCP tools: {names}")
        print(json.dumps({"mode": "deterministic tool-client demo", "tools": names}))

        async def call(name: str, body: dict) -> dict:
            response = await client.call_tool(name, body)
            if response.is_error:
                raise RuntimeError(f"{name} failed: {response.content}")
            payload = response.structured_content
            if payload is None:
                texts = [item.text for item in response.content if item.type == "text"]
                payload = json.loads("".join(texts))
            if not isinstance(payload, dict) or "error" in payload:
                raise RuntimeError(f"{name} returned an invalid response: {payload}")
            print(json.dumps({"tool": name, "result": payload}))
            return payload

        old = await call("recall", {"project": "demo", "revision": "r1"})
        later = await call("recall", {"project": "demo", "revision": "r2"})
        keyed = [
            decision for decision in old["decisions"] if decision["scope"] == "keyed-job-requests"
        ]
        if len(keyed) != 1:
            raise RuntimeError("Run scripts/seed_demo.py before this demonstration")
        impact = await call(
            "assess_changes",
            {
                "project": "demo",
                "request_id": "demo-v1-assess-r2",
                "base": old["revision"],
                "target": later["revision"],
            },
        )
        outcomes = {}
        affected = sorted({item["contract_id"] for item in impact["affected"]})
        for contract in affected:
            result = await call(
                "run_check",
                {
                    "project": "demo",
                    "request_id": f"demo-v1-{contract}-check-r2",
                    "revision": later["revision"],
                    "contract": contract,
                },
            )
            outcomes[contract] = result["outcome"]
        required = {"keyed-duplicates": "false", "unkeyed-duplicates": "true"}
        if any(outcomes.get(contract, "unknown") != value for contract, value in required.items()):
            print(
                json.dumps(
                    {
                        "proposal": None,
                        "reason": "Measured outcomes do not support narrowing",
                        "outcomes": {
                            contract: outcomes.get(contract, "unknown") for contract in required
                        },
                    }
                )
            )
            return
        await call(
            "propose_replacement",
            {
                "project": "demo",
                "request_id": "demo-v1-keyed-proposal-r2",
                "revision": later["revision"],
                "replaces": keyed[0]["id"],
                "statement": "Retry a keyed job request only with the same stable idempotency key.",
                "scope": "keyed-job-requests",
                "reason": "Same-key retries create one job. Unkeyed retries still create two.",
                "sources": [
                    {
                        "uri": f"git:{later['revision']}:job_api.py",
                        "note": "Measured same-key deduplication at r2",
                    }
                ],
                "supports": [[{"contract": "keyed-duplicates", "expected": False}]],
            },
        )
        await call("recall", {"project": "demo", "revision": later["revision"]})
        print(json.dumps({"state": "proposed", "next_step": "Review in the dashboard"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    args = parser.parse_args()
    asyncio.run(demonstrate(args.url))


if __name__ == "__main__":
    main()
