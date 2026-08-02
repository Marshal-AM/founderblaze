# syntax=docker/dockerfile:1
# Build from repo root:
#   docker build -f apps/chat/Dockerfile -t founderblaze-chat .
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY apps/chat/package.json apps/chat/package-lock.json ./
RUN npm ci

FROM node:22-bookworm-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/chat/ ./
ENV NEXT_TELEMETRY_DISABLED=1 \
    DATABASE_URL=postgresql://build:build@127.0.0.1:5432/build
RUN npm run build

FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3001 \
    HOSTNAME=0.0.0.0

RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3001
CMD ["node", "server.js"]
