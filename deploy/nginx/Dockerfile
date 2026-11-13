# Сборка SPA (React 19 + Vite, Node 26 LTS — HLD §4) и упаковка в nginx 1.30.
# KB_PUBLIC_URL — публичный адрес стенда. Адрес Keycloak для SPA (VITE_KC_BASE):
#   http://IP   → Keycloak напрямую, порт KC_HOST_PORT (дефолт 8080, без TLS)
#   https://…   → Keycloak за nginx по пути /auth (TLS-схема README §5)
# VITE_APP_BASE — база приложения (например '/know' — приложение по подпути
# merch-vibe.ru/know); пусто — корень.
# CORS backend'а (KB_FRONTEND_URL) — тот же адрес.
FROM node:26-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# KB_PUBLIC_URL приходит из compose build.args (docker-compose.yml) —
# здесь только объявление; без ARG переменная в RUN пуста всегда.
ARG KB_PUBLIC_URL=""
ARG VITE_APP_BASE=""
ARG KC_HOST_PORT="8080"
# Адрес Keycloak для браузера — по схеме KB_PUBLIC_URL; VITE_APP_BASE — база
# SPA (vite.config.ts: base + build.outDir = dist/<база>).
RUN case "$KB_PUBLIC_URL" in \
      https://*) export VITE_KC_BASE="$KB_PUBLIC_URL/auth/realms/kb" ;; \
      http://*)  export VITE_KC_BASE="$KB_PUBLIC_URL:${KC_HOST_PORT:-8080}/realms/kb" ;; \
      *) : ;; \
    esac \
    && if [ -n "$VITE_APP_BASE" ]; then export VITE_APP_BASE="${VITE_APP_BASE%/}/"; fi \
    && npm run build

FROM nginx:1.30-alpine
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
# TLS-fallback: без сертификатов в certs/ nginx не стартовал бы (restart-loop);
# openssl в образ (в nginx:1.30-alpine его нет — fallback умирал с exit 127).
RUN apk add --no-cache openssl
COPY deploy/nginx/tls-fallback.sh /docker-entrypoint.d/40-tls-fallback.sh
# sed убирает CR: git на Windows отдаёт скрипт с CRLF, shebang ломается (127)
RUN sed -i 's/\r$//' /docker-entrypoint.d/40-tls-fallback.sh && chmod +x /docker-entrypoint.d/40-tls-fallback.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443