# Temporal server for Railway / Docker.
# Needs its OWN Postgres — parse DATABASE_URL into discrete vars (never pass the URL as SEEDS).
#
# Required env (Railway example):
#   DB=postgres12
#   DB_PORT=5432                    # MUST set — image default is 3306
#   POSTGRES_USER=postgres
#   POSTGRES_PWD=...
#   POSTGRES_SEEDS=postgres-temporal.railway.internal
# Optional if SSL required after TCP connects:
#   POSTGRES_TLS_ENABLED=true
#   POSTGRES_TLS_DISABLE_HOST_VERIFICATION=true
#
# Build: docker build -f infra/temporal/Dockerfile -t founderblaze-temporal .
FROM temporalio/auto-setup:1.25.2

EXPOSE 7233
