#!/bin/bash
# Бэкап-контур (этап 11, NFR-012, HLD §8.2) — контейнер backup.
#
# Разделение ролей:
#   - pgBackRest (WAL-архив + базовые копии) выполняется в postgres-контейнере:
#     pgbackrest требует локальное соединение с кластером и доступ к pg1-path;
#     archive_command там же. Запуск копий — pgbackrest.sh в postgres-контейнере
#     (скрипт цикла с расписанием), см. compose service postgres.
#   - Этот контейнер: restic-снапшоты тома silo (сразу после успешной pgBackRest
#     копии — согласование по времени, единая точка восстановления) и textfile-
#     состояние для Prometheus (kb_backup_freshness_seconds / kb_backup_failed).
#
# Координация: pgbackrest.sh пишет маркер /backups/status/pgbackrest.done
# (timestamp последней успешной копии) и /backups/status/pgbackrest.failed
# при ошибке; этот контейнер ждёт свежий маркер текущего цикла, затем делает
# restic backup и пишет общий textfile-состояние.
set -u

STANZA="kb"
STATUS_DIR="/backups/status"
STATE_DIR="/backups/prometheus"
STATE_FILE="$STATE_DIR/backup_state.prom"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
DONE_MARKER="$STATUS_DIR/pgbackrest.done"
FAILED_MARKER="$STATUS_DIR/pgbackrest.failed"
mkdir -p "$STATE_DIR"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: $*"; }

write_state() {
    # $1 — freshness сек (0 = «нет данных»), $2 — failed 0/1
    cat > "$STATE_FILE.tmp" <<EOF
# HELP kb_backup_freshness_seconds Возраст последней успешной копии (сек)
# TYPE kb_backup_freshness_seconds gauge
kb_backup_freshness_seconds $1
# HELP kb_backup_failed Последний цикл копирования завершился ошибкой (0/1)
# TYPE kb_backup_failed gauge
kb_backup_failed $2
EOF
    mv "$STATE_FILE.tmp" "$STATE_FILE"
}

# --- Ожидание первого маркера pgBackRest (первый цикл postgres-контейнера) ---
log "ожидание первой копии pgBackRest (маркер $DONE_MARKER)"
for i in $(seq 1 120); do
    if [ -f "$DONE_MARKER" ]; then
        break
    fi
    if [ -f "$FAILED_MARKER" ]; then
        log "pgBackRest сообщил об ошибке — цикл прерван"
        write_state 0 1
        rm -f "$FAILED_MARKER"
        # продолжаем ждать следующий цикл
    fi
    sleep 10
done

# --- Инициализация restic (репозиторий в общем томе) ---
if ! restic snapshots >/dev/null 2>&1; then
    log "restic init"
    restic init || { log "restic init FAILED"; write_state 0 1; exit 1; }
fi

# --- Цикл: ждём маркер pgBackRest текущего цикла → restic → состояние ---
LAST_DONE_TS=0
while true; do
    # Ждём новый маркер (mtime новее предыдущего)
    WAITED=0
    while true; do
        if [ -f "$DONE_MARKER" ]; then
            TS=$(stat -c %Y "$DONE_MARKER")
            if [ "$TS" -gt "$LAST_DONE_TS" ]; then
                LAST_DONE_TS=$TS
                break
            fi
        fi
        # Ошибка pgBackRest в этом цикле — failed=1, ждём следующий
        if [ -f "$FAILED_MARKER" ]; then
            write_state "$( [ -f "$DONE_MARKER" ] && stat -c %Y -c '' >/dev/null 2>&1; echo 0)" 1
            rm -f "$FAILED_MARKER"
            break
        fi
        sleep 10
        WAITED=$((WAITED + 10))
        # Сигнальная метка раз в 10 мин — видно в логах, что контейнер жив
        if [ $((WAITED % 600)) -eq 0 ]; then
            log "ожидание маркера pgBackRest (${WAITED}s)"
        fi
    done

    if restic backup /silo-data --tag silo; then
        log "restic OK"
        restic forget --keep-daily 7 --keep-weekly 8 --prune >/dev/null 2>&1 || true
        FAILED=0
    else
        log "restic FAILED"
        FAILED=1
    fi

    # Свежесть: возраст маркера (создаётся сразу после успешной pgBackRest копии)
    if [ "$FAILED" = "0" ] && [ -f "$DONE_MARKER" ]; then
        TS=$(stat -c %Y "$DONE_MARKER")
        NOW=$(date +%s)
        FRESH=$((NOW - TS))
        write_state "$FRESH" 0
        log "cycle OK, freshness=${FRESH}s"
    else
        write_state 0 1
        log "cycle FAILED"
    fi
done
