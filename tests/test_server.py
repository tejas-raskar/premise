from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import Client
from mcp.shared.exceptions import MCPError
from redis.exceptions import ConnectionError
from test_memory import decision_body

from premise.server import create_app


def test_http_contract_and_boundary_errors(memory, monkeypatch):
    instance, _ = memory
    with TestClient(create_app(instance)) as client:
        projects = client.get("/api/projects").json()["projects"]
        assert projects[0]["id"] == "demo"
        assert [r["name"] for r in projects[0]["revisions"]] == ["r1", "r2"]
        body = decision_body()
        recorded = client.post("/api/record_decision", json=body)
        assert recorded.status_code == 200
        old = recorded.json()["decision"]["id"]
        assert client.post("/api/record_decision", json=body).json() == recorded.json()
        assert (
            client.post("/api/record_decision", json={**body, "scope": "different"}).status_code
            == 409
        )
        invalid = client.post(
            "/api/run_check",
            json={
                "project": "demo",
                "request_id": "bad",
                "revision": "r1",
                "contract": "keyed-duplicates",
                "command": "anything",
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "validation"
        missing = client.post("/api/recall", json={"project": "absent", "revision": "r1"})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        check = client.post(
            "/api/run_check",
            json={
                "project": "demo",
                "request_id": "check",
                "revision": "r1",
                "contract": "keyed-duplicates",
            },
        )
        assert check.json()["outcome"] == "true"
        recalled = client.post(
            "/api/recall", json={"project": "demo", "revision": "r1", "decision_id": old}
        )
        assert recalled.json()["decisions"][0]["status"] == "supported"

        def disconnected(*args, **kwargs):
            raise ConnectionError("connection details must not be exposed")

        monkeypatch.setattr(instance._graphs["demo"], "ro_query", disconnected)
        unavailable = client.post("/api/recall", json={"project": "demo", "revision": "r1"})
        assert unavailable.status_code == 503
        assert unavailable.json() == {
            "error": {"code": "unavailable", "message": "Graph unavailable"}
        }


@pytest.fixture
def live_server(memory):
    instance, _ = memory
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(instance), log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    server.should_exit = True
    thread.join(10)
    listener.close()
    assert not thread.is_alive()


async def test_real_mcp_client_calls_all_five_tools(live_server):
    async with Client(live_server + "/mcp/") as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "record_decision",
            "recall",
            "assess_changes",
            "run_check",
            "propose_replacement",
        }
        body = decision_body()
        recorded = await client.call_tool("record_decision", body)
        assert not recorded.is_error
        old = recorded.structured_content["decision"]["id"]
        checked = await client.call_tool(
            "run_check",
            {
                "project": "demo",
                "request_id": "mcp-check-r1",
                "revision": "r1",
                "contract": "keyed-duplicates",
            },
        )
        assert checked.structured_content["outcome"] == "true"
        recalled = await client.call_tool(
            "recall", {"project": "demo", "revision": "r1", "decision_id": old}
        )
        assert recalled.structured_content["decisions"][0]["status"] == "supported"
        impact = await client.call_tool(
            "assess_changes",
            {"project": "demo", "request_id": "mcp-impact", "base": "r1", "target": "r2"},
        )
        assert impact.structured_content["affected"][0]["decision_id"] == old
        checked = await client.call_tool(
            "run_check",
            {
                "project": "demo",
                "request_id": "mcp-check-r2",
                "revision": "r2",
                "contract": "keyed-duplicates",
            },
        )
        assert checked.structured_content["outcome"] == "false"
        proposal = await client.call_tool(
            "propose_replacement",
            decision_body(
                revision="r2",
                replaces=old,
                reason="The same key now returns the same job",
                statement="Retry requests with the same stable key",
                supports=[[{"contract": "keyed-duplicates", "expected": False}]],
            ),
        )
        assert not proposal.is_error
        assert proposal.structured_content["state"] == "proposed"
        assert proposal.structured_content["replacement"]["state"] == "proposed"
        async with httpx.AsyncClient(base_url=live_server) as http:
            accepted = await http.post(
                "/api/accept_proposal",
                json={
                    "project": "demo",
                    "request_id": "mcp-accept",
                    "proposal_id": proposal.structured_content["proposal_id"],
                },
            )
            assert accepted.json()["state"] == "accepted"
        recalled = await client.call_tool(
            "recall", {"project": "demo", "revision": "r2", "decision_id": old}
        )
        assert recalled.structured_content["decisions"][0]["status"] == "superseded"
        with pytest.raises(MCPError, match="Extra inputs"):
            await client.call_tool(
                "recall", {"project": "demo", "revision": "r1", "unexpected": True}
            )
