# A2MCP list prices (USD per call)

Source of truth: `packages/schemas/src/index.ts` (`SERVICE_MANIFESTS`).  
Keep each `services/*/service.manifest.json` in sync when changing prices.

| Service | Price | SLA (minutes) |
|---|---|---|
| promo-video | $2.99 | 15 |
| automated-product-demo | $1.49 | 30 |
| social-listening | $1.00 | 15 |
| outreach | $1.00 | 15 |
| competitor-research | $1.00 | 20 |
| brand-kit | $1.49 | 15 |

When changing a price: update `SERVICE_MANIFESTS` + the matching `service.manifest.json`.
