# Agent-as-a-Service Platform — Architecture & Feature 5 Implementation Plan

Two parts:
1. A production-grade repo/server foundation that accommodates all 7 services (and future ones) without a rewrite — exposed as **OKX.AI A2MCP** services.
2. A full end-to-end plan for **Feature 5 — Automated Competitor Research Report**, with every data source, API, and edge case.

**Go-to-market model (replaces custom payment rails):** this platform is an **ASP (Agent Service Provider)** on [OKX.AI](https://www.okx.ai), registering services as **A2MCP** (Agent-to-MCP): standardized MCP/API endpoints with **fixed price per call**, settled instantly via the **OKX Payment SDK** on **X Layer** (`eip155:196`) in **USD₮0**. No custom facilitators, no Tron/Base USDT watchers, no prepaid-balance ledger as the primary payment path.

---

## PART 0 — OKX.AI / A2MCP CONTEXT (read first)

### 0.1 A2A vs A2MCP — which mode we use

| | A2A (Agent-to-Agent) | A2MCP (Agent-to-MCP) ← **this platform** |
|---|---|---|
| Best for | Complex negotiated tasks (e.g. design a brand logo) | Standardized MCP/API services (data, reports, utilities) |
| Pricing | Negotiated or fixed per task | **Fixed price per call** |
| Payment | Escrow on X Layer; released on user approval | **Pay-per-call or free**; paid endpoints must be x402-compliant (**OKX Payment SDK recommended**) |
| Operation | Semi-automated intake / negotiation | **Fully automatic** after listing |
| Arbitration / rating | Yes (5% bounty deposit if ASP files) | **None** — settled instantly per call |

**Decision:** All 7 products ship as **A2MCP** services (one ASP identity, multiple services). Use **A2A** later only if a product truly needs negotiation/escrow (e.g. open-ended custom brand work). Feature 5 and the other pipelines fit A2MCP because each call has a structured input → structured result (PDF URL / job status / artifacts).

### 0.2 What an A2MCP endpoint must look like

Per [OKX A2MCP Guide](https://web3.okx.com/onchainos/dev-docs/okxai/howtomcp), every listed endpoint is one of:

1. **Free** — `HTTP 200` + result directly; no billing, no payment headers.
2. **Paid (x402)** — no payment proof → `HTTP 402` with `PAYMENT-REQUIRED` (base64 v2 challenge). Buyer pays, replays request with payment proof → `HTTP 200` + result. Settlement is brokered by OKX; you do **not** build chain watchers.

**Self-check before ASP registration:**
```bash
curl -i -X POST https://your-domain/v1/services/competitor-research/jobs
# Free  → 200 + body
# Paid  → 402 + PAYMENT-REQUIRED header
```

### 0.3 ASP onboarding sequence (ops, not code)

1. **Install Onchain OS** (agent skill):
   ```text
   npx skills add okx/onchainos-skills --yes -g
   ```
2. **Log in to Agentic Wallet** (email ready):
   ```text
   Log in to Agentic Wallet on Onchain OS with my email
   ```
3. **Register as A2MCP ASP** (name, description, per-call price, HTTPS endpoint):
   ```text
   Help me register an A2MCP ASP on OKX.AI using OKX Agent Identity from Onchain OS
   ```
4. **List on OKX.AI** (review ≤24h; email + agent thread notify):
   ```text
   Help me list my ASP on OKX.AI using Onchain OS
   ```
5. **Live:** callers hit your HTTPS endpoint; paid calls settle in real time via Payment SDK; free calls just return data. Discoverable by Agent ID even before marketplace approval.

### 0.4 Payment SDK integration (seller side)

**Do not** hand-roll 402 challenges, EIP-3009 verify, or settlement. Use OKX packages:

```bash
npm install express @okxweb3/x402-express @okxweb3/x402-core @okxweb3/x402-evm
```

**Constraints (from OKX seller docs):**
- Network: **`eip155:196`** (X Layer mainnet); test with **`eip155:1952`**
- Default asset: **USD₮0** `0x779ded0c9e1022225f8e0630b35a9b54be713736` (6 decimals)
- Price as USD string (e.g. `"$4.99"`) — SDK converts to atomic units
- Schemes we care about: **`exact`** (fixed per call), optionally **`upto`** (metered cap for variable-cost jobs), **`aggr_deferred`** (batch micro-payments)
- Facilitator auth: `OKX_API_KEY` + `OKX_SECRET_KEY` + `OKX_PASSPHRASE` (HMAC); payee = Agentic Wallet / EVM address in `PAY_TO`
- Call `await resourceServer.initialize()` after the HTTP server starts, before serving paid traffic

**Minimal Express pattern** (gateway wraps each paid route):

```typescript
import express from "express";
import { paymentMiddleware, x402ResourceServer } from "@okxweb3/x402-express";
import { ExactEvmScheme } from "@okxweb3/x402-evm/exact/server";
import { OKXFacilitatorClient } from "@okxweb3/x402-core";

const NETWORK = "eip155:196"; // use eip155:1952 on testnet
const PAY_TO = process.env.PAY_TO!;

const facilitatorClient = new OKXFacilitatorClient({
  apiKey: process.env.OKX_API_KEY!,
  secretKey: process.env.OKX_SECRET_KEY!,
  passphrase: process.env.OKX_PASSPHRASE!,
});
const resourceServer = new x402ResourceServer(facilitatorClient);
resourceServer.register(NETWORK, new ExactEvmScheme());

const app = express();
app.use(
  paymentMiddleware(
    {
      "POST /v1/services/competitor-research/jobs": {
        accepts: [{
          scheme: "exact",
          network: NETWORK,
          payTo: PAY_TO,
          price: "$4.99", // fixed per-call A2MCP price
        }],
        description: "Automated competitor research report (PDF)",
        mimeType: "application/json",
      },
    },
    resourceServer,
  ),
);
// business handlers only run after payment verifies
```

**Prompt-style bootstrap** (from `docs/payment-sdk-prompt.md`): point an agent at the language-specific `SELLER.md` and ask it to wire charging for a concrete route, e.g.:

```text
Reference https://raw.githubusercontent.com/okx/payments/main/typescript/SELLER.md
I have POST /v1/services/competitor-research/jobs. Use onchain-payment-sdk to charge
$4.99 USDT0 per call, network X Layer (eip155:196), recipient <PAY_TO>.
```

Verify locally:
```bash
curl -i http://localhost:4021/v1/services/competitor-research/jobs
# expect HTTP 402 + payment-required: <base64>
```

### 0.5 Long-running jobs vs A2MCP pay-per-call

A2MCP settlement is **per HTTP call**, not per multi-minute workflow. Pipelines that take 30s–20+ minutes must still fit the protocol:

| Pattern | How it works | Use when |
|---|---|---|
| **A. Paid create → free poll** (recommended) | `POST .../jobs` is paid (`exact`); returns `{ job_id }` quickly after payment. `GET .../jobs/{id}` is **free** (or tiny fixed price). Webhook on completion optional. | Features 1–5, 2 (screen-rec), anything async |
| **B. Sync paid call** | Full result in the same paid request | Fast services (feature 7 single X post if &lt; ~30s) |
| **C. `upto` metered** | Buyer signs a cap; settle actual cost ≤ cap via settlement overrides | Wide cost variance (competitor research, heavy scrapes) |
| **D. A2A instead** | Escrow + delivery approval | Only if negotiation / human acceptance is required |

**Platform default:** Pattern A for all Temporal-backed products. Payment is captured when the job is **accepted**, not when the PDF finishes — price the call to cover expected COGS + margin; use internal cost tracking (not on-chain reserve/capture) for margin visibility. For Feature 5, consider Pattern C (`upto`) once volume justifies it.

### 0.6 Secrets / env (never commit)

```bash
OKX_API_KEY=...
OKX_SECRET_KEY=...
OKX_PASSPHRASE=...
PAY_TO=0x...                    # Agentic Wallet receive address on X Layer
NETWORK=eip155:196              # or eip155:1952 for testnet
```

> You shared an OKX API key in chat. Treat it as exposed: rotate in the [OKX Developer Portal](https://web3.okx.com/zh-hans/onchainos/dev-portal) if this chat/logs are shared, and store only in a secrets manager / local `.env` (gitignored). You still need **secret key** and **passphrase** for the facilitator client — API key alone is not enough.

### 0.7 Deploy requirements for ASP review

- Public **HTTPS** domain (not localhost)
- Prefer Singapore / Tokyo / US nodes if the service calls OpenAI/Gemini/Claude (Hong Kong nodes are often blocked by those vendors)
- Endpoint must already return compliant 402/200 before registration

---

## PART 1 — PLATFORM FOUNDATION

### 1.1 Design principles that shape every decision below

- **Every "product" is a workflow, not a script.** Promo video, YouTube auto-publish, Reddit listening, investor outreach, competitor research, brand kit, X posting — all 7 are DAGs of agent steps with retries, partial failure, and (in 2 cases) a human-approval gate. Treat them uniformly: one workflow engine, one job model, one A2MCP billing hook — not 7 bespoke pipelines.
- **Payment and execution are decoupled at the HTTP boundary.** The OKX Payment SDK middleware admits the request only after payment verifies; then the gateway enqueues a Temporal workflow. Same business logic for marketplace agents and any direct HTTPS caller.
- **Everything that publishes publicly (Reddit/HN comments, tweets, YouTube videos, cold emails) goes through a policy + approval layer.** This isn't optional — it's what keeps you out of ToS bans and spam-flagging.
- **Cost visibility per job, always.** Every external API call (LLM tokens, ElevenLabs, Higgsfield/Runway, proxies, Crunchbase/Similarweb) is metered against the job so you know margin vs the fixed A2MCP list price in real time.

### 1.2 High-level architecture

```
   OKX.AI marketplace /     ┌─────────────────────────────┐
   other agents / humans ──▶│  API Gateway (public HTTPS) │── auth, rate limit,
                            │  REST + MCP-shaped tools    │   idempotency, validation
                            └────────────┬────────────────┘
                                         │
                            ┌────────────▼────────────────┐
                            │  OKX Payment Middleware     │── @okxweb3/x402-*
                            │  (402 challenge / settle)   │   X Layer USD₮0 via
                            └────────────┬────────────────┘   OKXFacilitatorClient
                                         │ (job admitted after pay)
                            ┌────────────▼────────────────┐
                            │  Orchestrator (Temporal)    │── durable workflow per
                            │  1 workflow def / product   │   product, retries, timers,
                            └────────────┬────────────────┘   human-approval signals
                                         │
        ┌───────────┬────────────┬──┴─────────┬────────────┬────────────┬───────────┐
        ▼           ▼            ▼            ▼            ▼            ▼           ▼
   promo-video  screen-rec   social-listen  outreach   competitor-  brand-kit   social-post
   -service     -service     -service       -service    research     -service    -service
                                                         -service
        │           │            │            │            │            │           │
        └───────────┴─────┬──────┴────────────┴─────┬──────┴────────────┴───────────┘
                           ▼                          ▼
                 packages/connectors/*      packages/llm-core
                 packages/payments/okx/     (Payment SDK wrappers, route price map,
                 (typed clients…)            ASP manifest helpers)
                           │
                 ┌─────────▼─────────┐
                 │  Data layer:       │
                 │  Postgres (jobs,   │
                 │  cost ledger*)     │
                 │  Supabase Storage (PDF bytes → signed URL)    │
                 │  Redis / Temporal  │
                 └────────────────────┘
```

\*Internal **cost** ledger for COGS/margin only — not a customer prepaid wallet. On-chain money movement is entirely OKX Payment SDK + facilitator.

### 1.3 Monorepo structure

```
agent-services-platform/
├── apps/
│   ├── api-gateway/                # ONLY internet-facing entrypoint (HTTPS)
│   │   ├── src/
│   │   │   ├── routes/             # /v1/services/{service}/jobs, /v1/jobs/{id}, webhooks
│   │   │   ├── middleware/         # auth, rate-limit, idempotency, okxPayment
│   │   │   ├── payments/           # route → price map, ExactEvmScheme registration
│   │   │   ├── openapi.ts          # OpenAPI 3.1 (agent discovery + ASP docs)
│   │   │   └── server.ts           # initialize x402ResourceServer after listen
│   │   ├── Dockerfile
│   │   └── package.json
│   │
│   ├── orchestrator/               # Temporal worker host
│   │   ├── src/
│   │   │   ├── workflows/
│   │   │   ├── activities/
│   │   │   └── worker.ts
│   │   └── Dockerfile
│   │
│   ├── cost-worker/                # internal COGS aggregation / margin alerts (not chain)
│   │   └── Dockerfile
│   │
│   └── ops-dashboard/              # approve Reddit/HN/outreach; margins; API budgets
│       └── Dockerfile
│
├── services/                       # one folder per product; identical internal shape
│   ├── promo-video-service/
│   ├── automated-product-demo-service/
│   ├── social-listening-service/
│   ├── outreach-service/
│   ├── competitor-research-service/  # FULL DETAIL IN PART 2
│   ├── brand-kit-service/
│   ├── social-post-service/
│   └── _service-template/
│       ├── src/
│       │   ├── agents/
│       │   ├── pipeline.ts
│       │   ├── schema.ts           # Zod: input, output, cost-estimate
│       │   ├── pricing.ts          # list_price_usd (A2MCP) + variable COGS drivers
│       │   └── policy.ts
│       ├── tests/
│       ├── Dockerfile
│       └── service.manifest.json   # {name, version, a2mcp_price_usd, endpoint_path, sla_minutes}
│
├── packages/
│   ├── connectors/                 # typed external API clients + cost-per-call metadata
│   ├── payments/
│   │   └── okx/                    # thin wrappers around @okxweb3/x402-*
│   │       ├── facilitator.ts      # OKXFacilitatorClient from env
│   │       ├── routes.ts           # RoutesConfig built from service.manifest.json prices
│   │       └── schemes.ts          # ExactEvmScheme (+ optional Upto later)
│   ├── llm-core/
│   ├── schemas/
│   ├── queue/
│   ├── observability/
│   └── policy/
│
├── infra/
│   ├── docker/docker-compose.yml
│   ├── k8s/
│   ├── terraform/
│   └── ci/
│
├── docs/
│   ├── openapi.yaml
│   ├── pricing.md                  # A2MCP list prices vs COGS targets
│   ├── asp-onboarding.md           # Onchain OS prompts + listing checklist
│   ├── runbooks/
│   └── adr/
│
├── tests/e2e/
├── .env.example
├── turbo.json
└── README.md
```

### 1.4 The job lifecycle (A2MCP-compatible)

```
POST /v1/services/{service}/jobs
  Headers: X-Idempotency-Key
           (+ PAYMENT-* headers after buyer fulfills 402 — handled by SDK)
  Body: { input: <service-specific schema>, callback_url?, priority? }
  →
  402 Payment Required   (SDK: PAYMENT-REQUIRED header, USD₮0 on eip155:196)
  202 Accepted           { job_id, list_price_usd, eta_seconds, status_url }
                         // only after payment verified

GET  /v1/jobs/{job_id}        → free (or micro-priced) status poll
POST /v1/jobs/{job_id}/cancel → best-effort cancel; no on-chain refund for A2MCP
                                 (price for risk into list price; optional goodwill credits off-platform)
POST /v1/jobs/{job_id}/approve  (human-in-the-loop services only)
```

Why async job + poll/webhook: pipelines take 30s–20+ minutes; a single synchronous paid HTTP call would time out for buyers and for ASP review health checks that expect a quick 402/200 handshake. **Charge on create; deliver asynchronously.**

### 1.5 Payment layer — OKX Payment SDK only

**Removed from the old plan:** custom x402 facilitators, TRC-20/ERC-20 USDT deposit address generation, chain watchers, prepaid customer balances as the primary rail, double-entry customer ledger for on-chain funds.

**What we keep / add:**

1. **Per-route `exact` pricing** in `packages/payments/okx/routes.ts`, sourced from each `service.manifest.json` (`a2mcp_price_usd`).
2. **OKXFacilitatorClient** with API credentials; settlement on X Layer USD₮0.
3. **Optional later:** `upto` scheme + `settlement-overrides` for Feature 5 when actual COGS varies widely — buyer signs a cap; you settle ≤ cap after the job finishes (still one A2MCP product, metered).
4. **Internal cost ledger** (Postgres): append-only COGS events per job for margin dashboards — not customer balances.
5. **Idempotency:** `X-Idempotency-Key` on create so a retried paid request after network blip does not double-enqueue a Temporal workflow (SDK handles payment replay; we must still dedupe business jobs).

**Pricing policy for A2MCP list price:**
- Fixed per call at registration time (marketplace shows this price).
- Set high enough to cover p95 COGS + margin; use caching (Part 2) to protect margin.
- Changing price later = update middleware route config **and** re-submit ASP service metadata via Onchain OS.

### 1.6 Connector layer (`packages/connectors`)

Unchanged in intent: one typed client per external dependency with `call()`, retry/backoff, **cost-per-call metadata**, mock mode. Swappable vendors (Higgsfield ↔ Runway) without touching service pipelines.

### 1.7 Human-in-the-loop approval subsystem

Features 3 and 4 (and optionally 2 / 7) still need approval gates. Model as Temporal `awaiting_approval` + ops-dashboard / Telegram. **This is orthogonal to A2MCP payment** — payment already settled on job create; approval only gates public publish. Stale drafts auto-expire 24–48h.

### 1.8 Cross-cutting edge cases (platform-wide)

| Category | Edge case | Mitigation |
|---|---|---|
| Payment | Buyer never completes 402 | No job created; nothing to refund |
| Payment | Payment verifies but enqueue fails | Idempotent create + alert; optional off-platform credit; do not custom-chain-refund |
| Payment | Wrong network / asset | SDK rejects; only `eip155:196` + USD₮0 configured |
| Cost | Job COGS &gt; list price | Hard budget ceiling (e.g. 150% of expected COGS); partial output + ops alert; raise A2MCP price or switch to `upto` |
| Platform ToS | Auto-publishing YouTube/Reddit/X | `packages/policy` rate limits + disclosure |
| Platform ToS | Scraping LinkedIn (Feature 4) | Prefer official/public sources; flag legal risk |
| Content safety | Spam / false claims | Policy checks before approval queue |
| Reliability | Third-party API down mid-workflow | Temporal retries + circuit breakers; partial completion |
| Multi-tenancy | Cross-tenant artifacts | tenant id on every row + Supabase object prefixes / RLS |
| Secrets | OKX + vendor keys | Secrets manager; never commit; rotate if leaked |
| ASP review | Non-compliant endpoint | Pre-flight `curl -i` 402/200 checks in CI against staging HTTPS |
| Observability | Margin shrink | Cost middleware → per-service margin vs fixed list price |

---

## PART 2 — DEEP DIVE: Feature 5, Automated Competitor Research Report

**Pipeline:** Competitor Finder → Feature-Diff Agent → Pricing Scraper → Positioning Strategist → Report Compiler  
**Input:** product name and/or URL  
**Output:** branded PDF report  
**A2MCP surface:** paid `POST /v1/services/competitor-research/jobs` → `{ job_id }`; free `GET /v1/jobs/{id}` → status + `pdf_url` when complete.

### 2.1 Pipeline overview

```
Input: { product_name, product_url }
   │
   ▼
[1] Competitor Finder ──────► candidate list (8-15) → scored & filtered to top 5-8
   │  outputs: [{name, url, confidence, source}]
   ▼
[2] Feature-Diff Agent ──────► normalized feature matrix across product + competitors
   │  outputs: {features: [...], matrix: {...}, citations}
   ▼
[3] Pricing Scraper ──────────► pricing tiers, currency, billing model, historical price changes
   │  outputs: {product_pricing, competitor_pricing[], price_positioning}
   ▼
[4] Positioning Strategist ───► SWOT, 2x2 map, messaging gaps, recommended angles
   │  outputs: {swot, positioning_matrix, recommended_positioning, risks}
   ▼
[5] Report Compiler ──────────► PDF → local/Supabase URL → job complete (+ optional webhook)
```

Each arrow is a Temporal **activity**; the whole run is one **workflow** (`competitorResearch.workflow.ts`).

### 2.2 Agent-by-agent breakdown

#### Agent 1 — Competitor Finder

**Goal:** Ranked, deduplicated 5–8 competitors with confidence + provenance.

**Method (production discovery):**
1. Fetch product site (homepage, meta, `/pricing`, `/about`) via Playwright connector.
2. Search `"<product> alternative"`, `"vs"`, `"competitor"`.
3. Pull alternatives lists from crowd-sourced competitor sites.
4. Cross-reference company-graph API (category / stage).
5. LLM score 0–1 on category / ICP / stage; drop noise.
6. Dedupe by root domain; merge sources into combined confidence.

**Data sources:**

| Source | Purpose | Access | Notes |
|---|---|---|---|
| Google CSE / Bing / SerpApi | Discovery queries | Paid API key | SerpApi simpler; direct cheaper at volume |
| Crunchbase | Similar companies, stage | Paid API | Primary for B2B/startups |
| G2 | Category alternatives | Partner API or careful public scrape | Prefer official API |
| Capterra / SaaSHub / AlternativeTo | Alternatives signal | Respectful scrape + cache | SMB / dev-tool coverage |
| Product Hunt API | Early-stage launches | Free, rate-limited | Indie competitors |
| GitHub API | OSS competitors | PAT | Dev-tooling essential |
| App store scrapers | Mobile similar apps | Libraries | Only if mobile surface |
| Product's own site | Self-description | Direct fetch | Always first |

**Output schema:**
```json
{
  "competitors": [
    {"name": "string", "url": "string", "confidence": 0.0, "sources": ["crunchbase","g2"], "category_match": "string"}
  ]
}
```

**Edge cases:** zero/one competitor → widen once then report narrow category; 30+ candidates → strict ICP filter; wrong URL → flag mismatch; platform feature vs standalone → tag for pricing/diff agents.

#### Agent 2 — Feature-Diff Agent

**Goal:** Feature matrix with has/partial/no + evidence URL + scrape timestamp.

**Method:** Fetch features/docs/changelog → structured LLM extract (no invented features) → normalize synonyms → cite every cell. Cross-check G2/Capterra compare pages; Wayback for removed features.

**Sources:** Playwright / Firecrawl-or-equivalent fallback; G2/Capterra; Wayback; strongest reasoning model for extract+normalize.

**Output schema:**
```json
{
  "features": ["SSO","API access","Webhooks"],
  "matrix": {
    "product": {"SSO": {"status":"yes","evidence_url":"...","scraped_at":"..."}},
    "competitor_a": {"SSO": {"status":"partial","evidence_url":"...","scraped_at":"..."}}
  },
  "conflicts": [{"feature":"SSO","competitor":"competitor_a","conflicting_sources":["..."]}]
}
```

**Edge cases:** login-gated → `unknown`; synonym mismatch → curated synonym dict + clustering; conflicting sources → surface conflict; never paste competitor marketing copy verbatim.

#### Agent 3 — Pricing Scraper

**Goal:** Tiers, price, period, currency, contact-sales flags, optional 12–24m price history via Wayback.

**Sources:** Same browser stack; Wayback CDX; FX API for regional prices; review-site price mentions as secondary signal.

**Output schema:**
```json
{
  "product_pricing": {"tiers": [{"name":"Pro","price":49,"currency":"USD","period":"month","notes":"..."}]},
  "competitor_pricing": [{"competitor":"competitor_a","tiers":[],"pricing_model":"per-seat","enterprise_custom":true}],
  "price_history_signals": [{"competitor":"competitor_a","change":"+20%","observed_between":["2025-06","2026-05"]}]
}
```

**Edge cases:** usage-based → formula + example; regional → label region; A/B pricing → note limitation; freemium → positioning signal, not null.

#### Agent 4 — Positioning Strategist

**Goal:** SWOT, 2×2 map, 3–5 positioning angles grounded in Agents 1–3 facts. Pure LLM synthesis — no new external calls. Honest “no differentiation” allowed.

#### Agent 5 — Report Compiler

**Goal:** HTML/CSS template → charts → Playwright PDF → local path or Supabase Storage URL → complete job.

**Section order:** Cover → Exec summary → Landscape map → Feature matrix → Pricing → SWOT → Recommendations → Risks → Appendix (sources + timestamps).

### 2.3 Orchestration (Temporal)

```typescript
export async function competitorResearchWorkflow(input: { productName: string; productUrl: string }) {
  const competitors = await executeActivity(findCompetitors, input, { retry: 3, timeout: "5m" });
  const [featureDiff, pricing] = await Promise.all([
    executeActivity(diffFeatures, { input, competitors }, { retry: 3, timeout: "10m" }),
    executeActivity(scrapePricing, { input, competitors }, { retry: 3, timeout: "10m" }),
  ]);
  const positioning = await executeActivity(buildPositioning, { featureDiff, pricing }, { timeout: "3m" });
  const report = await executeActivity(compileReport, {
    input, competitors, featureDiff, pricing, positioning,
  }, { timeout: "5m" });
  return report; // { pdf_url, cost_breakdown }
}
```

Feature-diff ∥ pricing after competitor list. Each activity reports COGS into the internal cost ledger for margin vs A2MCP list price.

### 2.4 Cost model & A2MCP list price

| Cost driver | Rough scale |
|---|---|
| Search/discovery | ~10–20 queries / job |
| Company-graph API | 1–8 lookups |
| Headless fetches | ~15–30 pages |
| Proxy / managed scrape | scales with fetches |
| LLM extract + synthesis | largest COGS line |
| PDF render | negligible |

**A2MCP pricing:**
- Register a **fixed** per-call price (start from p95 COGS × margin target; document in `docs/pricing.md`).
- Charge on `POST .../jobs` via Payment SDK `exact` (or `upto` with cap once ready).
- Cache raw per-competitor scrape data 24–72h to protect margin when multiple jobs share well-known competitors.
- No on-chain reserve/capture/refund loop — A2MCP settles the call instantly; manage overruns with budget ceilings + price updates.

### 2.5 Legal / ToS note

Prefer official APIs (Crunchbase, Product Hunt, GitHub) over scraping. Where scraping is unavoidable: robots.txt, aggressive cache, conservative volume. Treat ToS risk as ongoing ops, not day-one solved.

---

## PART 3 — BUILD / LAUNCH ORDER (A2MCP-first)

1. Scaffold monorepo + `api-gateway` + one health route on HTTPS staging.
2. Wire OKX Payment SDK on a **hello-world paid route**; verify `curl -i` → 402 / pay → 200 on X Layer testnet (`eip155:1952`).
3. Implement Feature 5 Temporal workflow + paid create / free status pattern.
4. Install Onchain OS → Agentic Wallet login → register **A2MCP ASP** pointing at staging/prod HTTPS → list on OKX.AI.
5. Add remaining six services behind the same gateway + route price map.
6. Ops dashboard + policy gates for publish-type services.
7. Mainnet cutover (`eip155:196`), rotate any leaked keys, monitor margin vs list price.
