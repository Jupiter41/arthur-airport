FROM node:22-slim AS builder

WORKDIR /app
COPY services/api-gateway/package*.json .
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY services/api-gateway/ .
COPY services/_common/ /app/_common/
COPY config/ /app/config/
RUN npx tsc
ARG ART_REVISION=unversioned
ARG ART_SOURCE_DIRTY=true
RUN node /app/_common/build_identity.mjs api-gateway "$ART_REVISION" "$ART_SOURCE_DIRTY"

FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV NODE_ENV=production

COPY services/api-gateway/package*.json .
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/_common ./_common
COPY --from=builder /app/config ./config
COPY --from=builder /app/build-identity.json ./build-identity.json
ENV ART_REQUIRE_BUILD_IDENTITY=1

ARG ART_REVISION=unversioned
LABEL org.opencontainers.image.revision=$ART_REVISION

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:3000/health || exit 1

CMD ["node", "dist/index.js"]
