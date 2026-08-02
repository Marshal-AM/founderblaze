# Railway deploy (FounderBlaze)

Full stack on Railway with **self-hosted Temporal**.

You need **7 services**:

| # | Service | Builder | Public? |
|---|---------|---------|---------|
| 1 | `postgres` | Railway Postgres plugin | — |
| 2 | `postgres-temporal` | Railway Postgres plugin | — |
| 3 | `temporal` | [`infra/temporal/Dockerfile`](../../infra/temporal/Dockerfile) | **no** |
| 4 | `api` | [`apps/api/Dockerfile`](../../apps/api/Dockerfile) | **yes** |
| 5 | `worker` | [`apps/worker/Dockerfile`](../../apps/worker/Dockerfile) | **no** |
| 6 | `agent` | [`apps/agent/Dockerfile`](../../apps/agent/Dockerfile) | **no** (private OK) |
| 7 | `chat` | [`apps/chat/Dockerfile`](../../apps/chat/Dockerfile) | **yes** |

Build context for all app Dockerfiles is the **repo root**.  
Genblaze path deps under `reference/` are gitignored — images use `uv sync --no-sources` (PyPI).

```text
User → chat (public)
         └─ AGENT_URL → agent (private)
                           └─ FOUNDERBLAZE_A2MCP_BASE_URL → api (public or private)
                                                              ├─ DATABASE_URL → postgres
                                                              └─ TEMPORAL_ADDRESS → temporal
worker ← TEMPORAL + DATABASE_URL + vendor keys
temporal → postgres-temporal
```

---

## 1. Postgres (jobs + chat)

Add a Railway **Postgres** plugin named `postgres`.

Wire on **api**, **worker**, and **chat**:

```bash
DATABASE_URL=${{postgres.DATABASE_URL}}
```

Jobs tables (`jobs`, …) and Auth.js / chat history tables share this database (no name collisions).

---

## 2. Self-host Temporal

### 2a. Temporal Postgres

Add a **second** Postgres plugin: `postgres-temporal`.  
Do **not** reuse the jobs database.

### 2b. Temporal server

New empty service → Dockerfile path `infra/temporal/Dockerfile`, context = repo root.  
Private networking only (no public HTTP). Same Railway project/environment as `postgres-temporal`.

Parse `postgres-temporal`’s `DATABASE_URL` into **discrete** vars — never put the full URL in `POSTGRES_SEEDS`.

Example URL:  
`postgresql://USER:PASSWORD@HOST:5432/railway`

```bash
DB=postgres12
DB_PORT=5432
# ⚠️ DB_PORT defaults to 3306 in auto-setup — you MUST set 5432
POSTGRES_USER=USER
POSTGRES_PWD=PASSWORD
POSTGRES_SEEDS=HOST
# host only, e.g. postgres-temporal.railway.internal
```

If it loops on `Waiting for PostgreSQL to startup`:

- `POSTGRES_SEEDS` is a full URL / wrong host / wrong environment
- `DB_PORT` missing (still 3306)
- Temporal not on the same private network as Postgres

If TCP connects but SSL fails:

```bash
POSTGRES_TLS_ENABLED=true
POSTGRES_TLS_DISABLE_HOST_VERIFICATION=true
```

Temporal creates DBs `temporal` + `temporal_visibility` (Railway’s default user can CREATE).

### 2c. App Temporal env (api + worker)

```bash
TEMPORAL_ADDRESS=<temporal-service>.railway.internal:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=founderblaze
# leave TEMPORAL_API_KEY and TEMPORAL_TLS unset for private auto-setup
```

Deploy Temporal **before** (or with) api/worker so workers can connect.

---

## 3. api

- Dockerfile: `apps/api/Dockerfile` (context = repo root)
- Generate a public domain
- Health: `GET /health`

```bash
PORT=${{PORT}}
DATABASE_URL=${{postgres.DATABASE_URL}}
TEMPORAL_ADDRESS=<temporal>.railway.internal:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=founderblaze
PUBLIC_API_BASE_URL=https://<api-public-host>
```

---

## 4. worker

- Dockerfile: `apps/worker/Dockerfile` (Debian + ffmpeg + Playwright Chromium)
- **No** public networking
- Give it **≥2 GB RAM** (Chromium + ffmpeg + long activities)

Same `DATABASE_URL` + `TEMPORAL_*` as api, plus all vendor keys from [`env.example`](../../env.example):

```bash
GEMINI_API_KEY=...
GEMINI_TEXT_MODEL=gemini-2.5-flash
GEMINI_IMAGE_MODEL=gemini-2.5-flash-image
B2_KEY_ID=...
B2_APP_KEY=...
B2_BUCKET=...
B2_REGION=...
B2_PUBLIC_URL_BASE=   # empty for private bucket + presigned URLs
LMNT_API_KEY=...
FIRECRAWL_API_KEY=...
EXA_SEARCH_API_KEY=...
TAVILY_API_KEY=...
SEGMIND_API_KEY=...
SERPER_API_KEY=...   # or BRAVE_SEARCH_API_KEY
# optional: JINA_API_KEY, etc.
```

Playwright browsers are installed **in the image** (`PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`). No host `playwright install` needed on Railway.

---

## 5. agent

- Dockerfile: `apps/agent/Dockerfile`
- Prefer **private** (chat proxies via server-side `AGENT_URL`)
- Listens on Railway `PORT` when `AGENT_PORT` is unset

```bash
PORT=${{PORT}}
FOUNDERBLAZE_A2MCP_BASE_URL=http://api.railway.internal:8080
AGENT_CORS_ORIGINS=https://founderblaze.up.railway.app
GEMINI_API_KEY=...
AGENT_GEMINI_MODEL=gemini-3.1-pro-preview
GEMINI_TEXT_MODEL=gemini-2.5-flash
```

Health: `GET /health`

> Railway injects `PORT` (often `8080`). Prefer hardcoding `http://api.railway.internal:<api-PORT>` — nested `${{api.PORT}}` references inside a URL string can resolve empty.

---

## 6. chat

- Dockerfile: `apps/chat/Dockerfile` (Next.js standalone)
- Public domain
- Binds Railway `PORT` via standalone `server.js`

```bash
PORT=${{PORT}}
DATABASE_URL=${{postgres.DATABASE_URL}}
AGENT_URL=http://agent.railway.internal:8080
AUTH_SECRET=<random-32+-bytes>
AUTH_URL=https://founderblaze.up.railway.app
# optional Google OAuth — redirect URI = https://founderblaze.up.railway.app/api/auth/callback/google
AUTH_GOOGLE_ID=...
AUTH_GOOGLE_SECRET=...
```

Do **not** put vendor API keys on chat; it only talks to the agent BFF.

---

## Local Docker smoke (optional)

```bash
# from repo root (linux/amd64 images match Railway)
docker build -f apps/api/Dockerfile -t founderblaze-api .
docker build -f apps/agent/Dockerfile -t founderblaze-agent .
docker build -f apps/worker/Dockerfile -t founderblaze-worker .
docker build -f apps/chat/Dockerfile -t founderblaze-chat .
```

On Apple Silicon Macs, force amd64 if you want Railway parity:

```bash
docker build --platform linux/amd64 -f apps/worker/Dockerfile -t founderblaze-worker .
```

Local (non-Docker) Mac still needs:

```bash
source .venv/bin/activate
playwright install chromium
```

---

## Verify

```bash
curl -s https://YOUR_API_HOST/health
curl -s https://YOUR_CHAT_HOST/   # HTML shell
```

From the chat UI, run **Social Listening** or **Product Demo**.  
If create returns a job but it stays `queued`, Temporal address / worker / task queue is wrong.  
If the job fails with missing Chromium, the worker image was built without `playwright install` (rebuild `apps/worker/Dockerfile`).

---

## CLI sketch

```bash
# install once: https://docs.railway.com/guides/cli
railway login
railway link   # or railway init

# After services exist and env is set:
railway up --service api --dockerfile apps/api/Dockerfile
railway up --service worker --dockerfile apps/worker/Dockerfile
railway up --service agent --dockerfile apps/agent/Dockerfile
railway up --service chat --dockerfile apps/chat/Dockerfile
railway up --service temporal --dockerfile infra/temporal/Dockerfile
```

Exact `railway` flags vary by CLI version; prefer the Railway dashboard Dockerfile path + root directory settings if `up` differs.
