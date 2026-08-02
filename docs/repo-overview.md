# FounderBlaze — Repo Overview

**Live control plane is Python** (`uv`): `apps/api` + `apps/worker` + `packages/founderblaze`, plus `apps/agent` (Gemini + MCP HTTP) and `apps/chat` (Next.js).

---

## Top level

| Path | Role |
|---|---|
| `apps/api`, `apps/worker` | Live Python FastAPI A2MCP gateway + Temporal worker |
| `apps/agent` | Agent FastAPI (Postman) + MCP streamable HTTP |
| `apps/chat` | Next.js chat UI (`NEXT_PUBLIC_AGENT_URL`) |
| `packages/founderblaze` | Single library: core, all services, a2mcp, mcp_server, agent runner |
| `docs/` | Contracts, planning, ADRs, runbooks, pricing |
| `infra/` | CI, Docker, k8s, Terraform |
| `reference/` | Genblaze / B2 reference material |
| `env.example` / `.env` | Env template / local secrets |
| `pyproject.toml` | uv Python workspace |

---

## `apps/` (live)

| Folder | Contains | Role |
|---|---|---|
| `api/` | FastAPI A2MCP | HTTP: discovery, create/poll jobs (port 4021) |
| `worker/` | Temporal Python worker | Durable job lifecycle → Genblaze `Pipeline.run()` |
| `agent/` | FastAPI agent | `/v1/agent/run`, `/v1/tools`, MCP at `/mcp` (port 4022) |
| `chat/` | Next.js App Router | Browser chat → agent via `NEXT_PUBLIC_AGENT_URL` |

---

## `packages/founderblaze`

Namespace `founderblaze.*`:

| Module | Role |
|---|---|
| `core` | Config, jobs store, schemas, B2, provenance, discovery |
| `apd` | Automated product demo Genblaze pipeline |
| `brand_kit` | Brand kit pipeline |
| `outreach` | Investor outreach pipeline |
| `social_listening` | Social listening pipeline |
| `promo_video` | Promo video pipeline |
| `competitor_research` | Competitor research pipeline |
| `a2mcp` | HTTP client + tool definitions for all 6 services |
| `mcp_server` | Real MCP server (stdio CLI `founderblaze-mcp` + HTTP mount) |
| `agent` | Gemini tool-loop runner |

Live CLIs are exposed via `[project.scripts]` (e.g. `founderblaze-apd-live`, `founderblaze-mcp`).

---

## A2MCP vs MCP

| Name | What it is |
|---|---|
| **A2MCP** | FounderBlaze async job HTTP protocol (`apps/api`) |
| **MCP** | Anthropic Model Context Protocol tool server (`founderblaze.mcp_server`) |

---

## Local run

See root [README.md](../README.md): `uv sync --all-packages`, start api/worker/agent, then `npm run dev` in `apps/chat`.
