# FounderBlaze

Python monorepo of **A2MCP services** (Genblaze pipelines → Backblaze B2), plus a **real MCP server**, an **agent FastAPI**, and a **Next.js chat UI**.

## Layout

```text
packages/founderblaze/   # single library: core + all services + a2mcp + mcp_server + agent
apps/api/                # A2MCP gateway (port 4021)
apps/worker/             # Temporal worker
apps/agent/              # Agent FastAPI + MCP HTTP (port 4022)
apps/chat/               # Next.js chat UI (port 3001)
reference/genblaze/      # Genblaze SDK (path dependency)
```

## Quick start

```bash
# 1. Infra
docker compose -f infra/docker/docker-compose.python.yml up -d

# 2. Env
cp env.example .env
# DATABASE_URL, B2_*, GEMINI_API_KEY, Temporal, vendor keys as needed

# 3. Python workspace
uv sync --all-packages

# 4. API + worker + agent
uv run --package founderblaze-api founderblaze-api
uv run --package founderblaze-worker founderblaze-worker
uv run --package founderblaze-agent founderblaze-agent
```

### Chat UI

```bash
cd apps/chat
cp .env.example .env.local
# set NEXT_PUBLIC_AGENT_URL=http://localhost:4022
npm install
npm run dev
```

Open http://localhost:3001

### Postman (agent)

- `GET http://localhost:4022/health`
- `GET http://localhost:4022/v1/tools`
- `POST http://localhost:4022/v1/agent/run`  
  body: `{ "message": "List available FounderBlaze services" }`

### Real MCP (Cursor / Claude)

Stdio server (lists one tool per A2MCP service):

```bash
uv run --package founderblaze founderblaze-mcp
```

Cursor `mcp.json` example:

```json
{
  "mcpServers": {
    "founderblaze": {
      "command": "uv",
      "args": ["run", "--package", "founderblaze", "founderblaze-mcp"],
      "env": {
        "FOUNDERBLAZE_A2MCP_BASE_URL": "http://localhost:4021",
        "GEMINI_API_KEY": ""
      }
    }
  }
}
```

MCP streamable HTTP is also mounted at `http://localhost:4022/mcp`.

### A2MCP gateway

```bash
curl -s http://localhost:4021/v1/discovery
curl -s -X POST http://localhost:4021/v1/services/automated-product-demo/jobs \
  -H 'content-type: application/json' \
  -d '{"input":{"website_url":"https://linear.app","script":"Show homepage and pricing."}}'
```

### Live CLIs (bypass Temporal)

```bash
uv run --package founderblaze founderblaze-apd-live --url 'https://linear.app' --script '...'
uv run --package founderblaze founderblaze-brand-kit-live --brand-name 'Solace' --description '...'
```

## Notes

- Task queue: `founderblaze`
- Storage: Backblaze B2 · Provenance: Genblaze manifests + sidecars (see `docs/genblaze-provenance.md`)
- Agent calls A2MCP over HTTP (`FOUNDERBLAZE_A2MCP_BASE_URL`, default `http://localhost:4021`)
