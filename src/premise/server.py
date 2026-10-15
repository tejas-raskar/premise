from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from anyio import to_thread
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from redis.exceptions import RedisError

from premise.demo import create_demo
from premise.memory import Memory
from premise.models import (
    AcceptProposal,
    AssessChanges,
    MemoryError,
    ProposeReplacement,
    Recall,
    RecordDecision,
    Requirement,
    RunCheck,
    Source,
)


def create_app(memory: Memory | None = None) -> FastAPI:
    if memory is None:
        project = create_demo(Path(os.getenv("PREMISE_DEMO_REPO", ".artifacts/demo-repo")))
        memory = Memory(
            [project],
            host=os.getenv("PREMISE_FALKOR_HOST", "127.0.0.1"),
            port=int(os.getenv("PREMISE_FALKOR_PORT", "6387")),
            graph_prefix=os.getenv("PREMISE_GRAPH_PREFIX", "premise"),
        )
    requests = {
        "record_decision": RecordDecision,
        "recall": Recall,
        "assess_changes": AssessChanges,
        "run_check": RunCheck,
        "propose_replacement": ProposeReplacement,
    }

    async def validate_mcp(context, call_next):
        if context.method == "tools/call":
            params = context.params or {}
            model = requests.get(params.get("name"))
            if model:
                try:
                    model.model_validate(params.get("arguments", {}))
                except ValidationError as error:
                    raise MCPError(-32602, str(error)) from error
        return await call_next(context)

    mcp = MCPServer(
        "Premise",
        instructions="Retrieve revision-scoped engineering memory and fixed check results.",
        middleware=[validate_mcp],
    )

    async def invoke(name: str, body: dict) -> CallToolResult:
        body.pop("invoke", None)
        try:
            result = await to_thread.run_sync(getattr(memory, name), body)
            failed = False
        except MemoryError as error:
            result, failed = {"error": {"code": error.code, "message": error.message}}, True
        except RedisError:
            result, failed = (
                {"error": {"code": "unavailable", "message": "Graph unavailable"}},
                True,
            )
        return CallToolResult(
            content=[TextContent(text=json.dumps(result))],
            structured_content=result,
            is_error=failed,
        )

    @mcp.tool()
    async def record_decision(
        project: str,
        request_id: str,
        revision: str,
        statement: str,
        scope: str,
        sources: list[Source],
        supports: list[list[Requirement]],
    ) -> CallToolResult:
        """Record a decision and the assumptions that support it at one revision."""
        return await invoke("record_decision", locals())

    @mcp.tool()
    async def recall(project: str, revision: str, decision_id: str | None = None) -> CallToolResult:
        """Retrieve decisions, evidence, and replacement history for a revision."""
        return await invoke("recall", locals())

    @mcp.tool()
    async def assess_changes(
        project: str, request_id: str, base: str, target: str
    ) -> CallToolResult:
        """Traverse explicit file dependencies and record affected decisions."""
        return await invoke("assess_changes", locals())

    @mcp.tool()
    async def run_check(
        project: str, request_id: str, revision: str, contract: str
    ) -> CallToolResult:
        """Run one configured contract check at the exact repository revision."""
        return await invoke("run_check", locals())

    @mcp.tool()
    async def propose_replacement(
        project: str,
        request_id: str,
        revision: str,
        replaces: str,
        statement: str,
        scope: str,
        reason: str,
        sources: list[Source],
        supports: list[list[Requirement]],
    ) -> CallToolResult:
        """Propose an inactive decision in the same scope. A user must accept it."""
        return await invoke("propose_replacement", locals())

    mcp_app = mcp.streamable_http_app(streamable_http_path="/", json_response=True)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Premise", lifespan=lifespan)
    app.state.memory, app.state.mcp = memory, mcp

    @app.exception_handler(MemoryError)
    async def memory_error(request: Request, error: MemoryError):
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return JSONResponse(
            status_code=422, content={"error": {"code": "validation", "message": str(error)}}
        )

    @app.exception_handler(RedisError)
    async def unavailable(request: Request, error: RedisError):
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "unavailable", "message": "Graph unavailable"}},
        )

    @app.get("/api/projects")
    def projects():
        return memory.projects()

    @app.post("/api/record_decision")
    def http_record(request: RecordDecision):
        return memory.record_decision(request)

    @app.post("/api/recall")
    def http_recall(request: Recall):
        return memory.recall(request)

    @app.post("/api/assess_changes")
    def http_assess(request: AssessChanges):
        return memory.assess_changes(request)

    @app.post("/api/run_check")
    def http_check(request: RunCheck):
        return memory.run_check(request)

    @app.post("/api/propose_replacement")
    def http_propose(request: ProposeReplacement):
        return memory.propose_replacement(request)

    @app.post("/api/accept_proposal")
    def http_accept(request: AcceptProposal):
        return memory.accept_proposal(request)

    app.mount("/mcp", mcp_app)
    assets = Path("ui/dist")
    if assets.is_dir():
        app.mount("/", StaticFiles(directory=assets, html=True), name="dashboard")
    return app
