FROM node:22-slim AS builder

WORKDIR /app
COPY dashboards/art-dashboard/package*.json .
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY dashboards/art-dashboard/ .
COPY services/_common/ /app/_common/
COPY config/ /app/config/

# Accept Mapbox token as a build-time arg so Vite can inline it
ARG VITE_MAPBOX_TOKEN
ENV VITE_MAPBOX_TOKEN=$VITE_MAPBOX_TOKEN
ARG VITE_PUBLIC_DEPLOYMENT=false
ENV VITE_PUBLIC_DEPLOYMENT=$VITE_PUBLIC_DEPLOYMENT

RUN npm run build
ARG ART_REVISION=unversioned
ARG ART_SOURCE_DIRTY=true
RUN node /app/_common/build_identity.mjs dashboard "$ART_REVISION" "$ART_SOURCE_DIRTY"

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY dashboards/art-dashboard/nginx.conf /etc/nginx/conf.d/default.conf
ARG ART_REVISION=unversioned
LABEL org.opencontainers.image.revision=$ART_REVISION

EXPOSE 5173
CMD ["nginx", "-g", "daemon off;"]
