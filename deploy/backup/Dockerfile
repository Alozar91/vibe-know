# Инструментальный образ бэкап-контура (этап 11, NFR-012): pgBackRest для
# PostgreSQL (WAL-архив + базовые копии) + restic для тома silo (CAS-объекты).
# Поверх официального postgres:18.6 — pgbackrest требует локальное соединение
# с кластером и pg1-path, поэтому копии выполняются в postgres-контейнере
# (pgbackrest.sh), restic + textfile-состояние — в контейнере backup (backup.sh).
FROM postgres:18.6

# pgBackRest — из уже подключённого в postgres:18.6 PGDG-репозитория
# (apt.postgresql.org); restic — из Debian (trixie: restic 0.18);
# postgresql-18-pgvector — векторное расширение RAG (пост-MVP шаг [7]):
# CREATE EXTENSION vector в миграции 0011; restore на чистый узел тоже
# требует его (pg_restore воссоздаёт таблицу rag_chunks со столбцом vector).
RUN apt-get update \
    && apt-get install -y --no-install-recommends pgbackrest restic procps postgresql-18-pgvector \
    && rm -rf /var/lib/apt/lists/*

# Конфигурация pgBackRest (stanza kb: БД kb + keycloak — один кластер)
COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
RUN chmod 644 /etc/pgbackrest/pgbackrest.conf

# Скрипты: pgbackrest.sh (цикл копий — postgres-контейнер),
# backup.sh (restic + состояние — контейнер backup)
COPY pgbackrest.sh backup.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/pgbackrest.sh /usr/local/bin/backup.sh

# RESTIC_PASSWORD обязателен для restic — задаётся через окружение (deploy/.env)
CMD ["backup.sh"]
