# Proxy pool exhausted

1. Check connector circuit breaker logs (`packages/connectors`)
2. Pause non-critical scrape jobs in ops-dashboard
3. Fail soft with partial report rather than unbounded retries
