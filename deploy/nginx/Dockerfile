# Сборка SPA (React 19 + Vite, Node 26 LTS — HLD §4) и упаковка в nginx 1.30.
# KB_PUBLIC_URL — публичный адрес стенда (http://IP или https://домен) — задающий
# адрес Keycloak для SPA (VITE_KC_BASE) и CORS backend'а (KB_FRONTEND_URL).
FROM node:26-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Пустой KB_PUBLIC_URL → дефолт локального стенда (VITE_KC_BASE не задаётся)
RUN KB_PUBLIC_URL="$KB_PUBLIC_URL"; if [ -n "$KB_PUBLIC_URL" ]; then \
      export VITE_KC_BASE="$KB_PUBLIC_URL/auth/realms/kb"; fi \
    && npm run build

FROM nginx:1.30-alpine
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
