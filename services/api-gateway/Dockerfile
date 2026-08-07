FROM node:20-slim AS builder

WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
RUN npx tsc

FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV NODE_ENV=production

COPY package*.json .
RUN npm ci --omit=dev

COPY --from=builder /app/dist ./dist

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:3000/health || exit 1

CMD ["node", "dist/index.js"]
