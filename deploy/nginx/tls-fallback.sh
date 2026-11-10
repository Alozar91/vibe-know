#!/bin/sh
# TLS-fallback (README §5): нет сертификатов в /etc/nginx/certs — генерируем
# самоподписанный placeholder, чтобы nginx стартовал и до выпуска Let's Encrypt.
# Сертификат для домена обязателен: SPA-fetch на https://домен/auth при
# self-signed падает молча — заменить placeholder как можно скорее.
set -e

CERT_DIR=/etc/nginx/certs
if [ ! -f "$CERT_DIR/kb.crt" ] || [ ! -f "$CERT_DIR/kb.key" ]; then
    mkdir -p "$CERT_DIR"
    echo "$0: сертификаты не найдены — self-signed placeholder (CN=localhost)"
    openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
        -keyout "$CERT_DIR/kb.key" -out "$CERT_DIR/kb.crt" \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        >/dev/null 2>&1
fi
