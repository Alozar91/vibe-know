#!/bin/bash
# pgBackRest-цикл (этап 11, NFR-012, HLD §8.2) — выполняется в postgres-контейнере
# (pgbackrest требует локальное соединение с кластером и pg1-path).
#
# Расписание (единое с restic — согласование по времени, единая точка восстановления):
#   полная копия — по воскресеньям, инкремент — в остальные дни; интервал —
#   BACKUP_INTERVAL_SECONDS (deploy/.env). WAL-архив непрерывен (archive_command).
#
# Координация с контейнером backup (restic + textfile Prometheus):
#   маркеры в общем томе: /backups/status/pgbackrest.done (успех, mtime = момент
#   копии) и /backups/status/pgbackrest.failed (ошибка цикла).
set -u

STANZA="kb"
STATUS_DIR="/backups/status"
DONE_MARKER="$STATUS_DIR/pgbackrest.done"
FAILED_MARKER="$STATUS_DIR/pgbackrest.failed"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
mkdir -p "$STATUS_DIR"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pgbackrest: $*"; }

# --- Ожидание готовности кластера ---
for i in $(seq 1 60); do
    if pg_isready -q; then
        break
    fi
    log "waiting for cluster ($i/60)"
    sleep 5
done

# --- Инициализация stanza (идемпотентно) ---
# info без созданной stanza возвращает статус error — проверяем именно его
if ! pgbackrest --stanza="$STANZA" info 2>/dev/null | grep -q "status: ok"; then
    log "stanza-create"
    pgbackrest --stanza="$STANZA" stanza-create || { log "stanza-create FAILED"; touch "$FAILED_MARKER"; exit 1; }
fi

# --- Цикл копирования ---
while true; do
    FAILED=0
    DOW=$(date +%u)  # 1=пн .. 7=вс
    if [ "$DOW" = "7" ]; then
        TYPE_OPT="--type=full"
    else
        TYPE_OPT="--type=incr"
    fi

    log "backup ($TYPE_OPT)"
    if pgbackrest --stanza="$STANZA" backup $TYPE_OPT; then
        touch "$DONE_MARKER"
        log "backup OK"
    else
        touch "$FAILED_MARKER"
        FAILED=1
        log "backup FAILED"
    fi

    sleep "$INTERVAL"
done
