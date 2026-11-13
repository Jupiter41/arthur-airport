FROM node:22-slim AS builder

WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .

# Accept Mapbox token as a build-time arg so Vite can inline it
ARG VITE_MAPBOX_TOKEN
ENV VITE_MAPBOX_TOKEN=$VITE_MAPBOX_TOKEN
ARG VITE_PUBLIC_DEPLOYMENT=false
ENV VITE_PUBLIC_DEPLOYMENT=$VITE_PUBLIC_DEPLOYMENT

RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 5173
CMD ["nginx", "-g", "daemon off;"]
