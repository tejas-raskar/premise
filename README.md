# Premise

Engineering memory that records why a decision was made.
When related code changes, Premise identifies the decisions that need new evidence.

Premise connects coding agents to FalkorDB through five MCP tools.
The dashboard shows dependency paths, check results, and replacement proposals.
The included demo uses an owned, synthetic job API.

## Start

Install Git, Docker Compose, uv, and Node.js 22.12 or later.

1. Start FalkorDB.

   ```sh
   docker compose up -d --wait
   ```

2. Install the Python dependencies.

   ```sh
   uv sync --python 3.12
   ```

3. Create the demo and its initial memory.

   ```sh
   uv run python scripts/seed_demo.py
   ```

4. Build the dashboard.

   ```sh
   npm --prefix ui ci
   npm --prefix ui run build
   ```

5. Start the application.

   ```sh
   uv run uvicorn premise.server:create_app --factory --host 127.0.0.1 --port 8765
   ```

Open <http://127.0.0.1:8765>.
Connect an MCP client to <http://127.0.0.1:8765/mcp> through Streamable HTTP.
Run one application process. The local service has no account system.

## Verify

```sh
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
npm --prefix ui run build
```

Tests use the real FalkorDB instance on port 6387.
They create separate test graphs and temporary Git repositories.
See the [demo procedure](docs/demo.md) for the complete user flow.

## Limits

The MVP uses explicit file dependencies and fixed checks for the demo API.
Missing dependencies can hide an impact.
Checks execute trusted local code. They are not a security sandbox.
Keep the server bound to loopback.
Premise does not include an LLM. Your coding agent selects tools and interprets results.

Set `PREMISE_GRAPH_PREFIX` to use a separate memory graph.
Set `PREMISE_DEMO_REPO` to change the demo repository directory.
Use the same values for the seed script and server.
`PREMISE_FALKOR_HOST` and `PREMISE_FALKOR_PORT` select the database address.
The defaults are `127.0.0.1` and `6387`.

Stop the application with Ctrl+C.
Run `docker compose stop` to stop the database and preserve its volume.

## Documents

- [Terms](CONTEXT.md)
- [MVP brief](docs/brief.md)
- [Architecture](docs/architecture.md)
- [Graph model and queries](docs/graph.md)
- [Tool interface](docs/api.md)
- [Demo procedure](docs/demo.md)
- [Milestones](docs/progress.md)
- [Agent verification guide](.agents/skills/verify-premise/SKILL.md)

## AI assistance

AI coding agents assist with design, implementation, documentation, and review.
Verification results are recorded with each milestone.
