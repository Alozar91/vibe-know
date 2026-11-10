# Сборка SPA (React 19 + Vite, Node 26 LTS — HLD §4) и упаковка в nginx 1.30.
# KB_PUBLIC_URL — публичный адрес стенда. Адрес Keycloak для SPA (VITE_KC_BASE):
#   http://IP   → Keycloak напрямую, порт 8080 (без TLS)
#   https://…   → Keycloak за nginx по пути /auth (TLS-схема README §5)
# CORS backend'а (KB_FRONTEND_URL) — тот же адрес.
FROM node:26-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN case "$KB_PUBLIC_URL" in \
      https://*) export VITE_KC_BASE="$KB_PUBLIC_URL/auth/realms/kb" ;; \
      http://*)  export VITE_KC_BASE="$KB_PUBLIC_URL:8080/realms/kb" ;; \
      *) : ;; \
    esac && npm run build

FROM nginx:1.30-alpine
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
# TLS-fallback: без сертификатов в certs/ nginx не стартовал бы (restart-loop)
COPY deploy/nginx/tls-fallback.sh /docker-entrypoint.d/40-tls-fallback.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
