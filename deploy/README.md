# Развёртывание «Корпоративной базы знаний» (MVP)

Инструкция развёртывания single-node через Docker Compose (HLD §3.2, NFR-015/016).
Целевое окружение внедрения — шаг [6] плана MVP: здесь же процедуры резервного
копирования/восстановления (NFR-012/013) и настройки TLS/SMTP, отложенные в MVP.

## 1. Состав стека

| Сервис | Образ (HLD §4) | Порты (хост) | Назначение |
|---|---|---|---|
| postgres | `kb-pg-backup-tools:18.6` (postgres:18.6 + pgBackRest + restic) | 5432 | БД `kb` + отдельная БД `keycloak`; WAL-архив и базовые копии |
| keycloak | keycloak/keycloak:26.8 | 8080 | Аутентификация OIDC, realm `kb` |
| valkey | valkey/valkey:9.1 | 6379 | Брокер очередей + кэш |
| silo | pgsty/silo | — (внутр. 9000) | CAS-хранилище файлов (S3 API) |
| gotenberg | gotenberg/gotenberg:9.2 | — (внутр. 3000) | Конвертация офисных форматов в PDF |
| api | сборка `backend/` | 8001→8000 | REST API (FastAPI; при старте применяет миграции Alembic) |
| worker | сборка `backend/` | — (внутр. 9808) | Фоновые задачи Celery + экспозер метрик |
| nginx | сборка `deploy/nginx/` | 80 | Статика SPA, прокси `/api`, `/auth` |
| prometheus | prom/prometheus:v3 | 9090 | Метрики и правила алертинга (NFR-019) |
| alertmanager | prom/alertmanager | 9093 | Маршрутизация алертов (email СА — при настроенном SMTP) |
| blackbox | prom/blackbox-exporter | — | HTTP/TCP-пробы keycloak/converter/silo/nginx/valkey |
| node-exporter | prom/node-exporter | 9100 | Метрики узла + textfile свежести бэкапов |
| postgres-exporter | prometheuscommunity/postgres-exporter | 9187 | Метрики PostgreSQL |
| backup | `kb-pg-backup-tools:18.6` | — | restic-снапшоты silo + textfile-состояние копий |
| backup-init | тот же образ | — | Однократная подготовка тома `backups` (chown 999) |

Одноразовые сервисы: `silo-init` (создание бакета), `backup-init` (том копий).

## 2. Развёртывание с нуля

### 2.1. Предусловия

- Docker Engine 28+ / Docker Desktop (Linux или WSL2), compose v2.
- Свободные хост-порты: **80, 5432, 6379, 8001, 8080, 9090, 9093, 9100, 9187**.
  Порт 8000 в тестовой конфигурации занят внешним процессом — api отображён на 8001;
  при внедрении можно вернуть `8000:8000` в `docker-compose.yml`.

### 2.2. Параметры окружения

```bash
cp deploy/.env.example deploy/.env
# заполнить все change-me: пароли PostgreSQL, секреты клиентов Keycloak,
# SILO_ROOT_PASSWORD, BACKUP_RESTIC_PASSWORD
```

| Переменная | Назначение |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Основная БД (`kb`); БД `keycloak` создаётся init-скриптом |
| `KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` | Начальный администратор Keycloak (консоль `/realms/master/console`), не СА системы |
| `KB_API_CLIENT_SECRET` / `KB_CLI_CLIENT_SECRET` | Секреты клиентов `kb-api` / `kb-cli` realm `kb` (подставляются в realm-импорт) |
| `KB_TEST_PASSWORD` | Пароль сид-пользователей realm (список — §7) — **только тестовый realm** |
| `SILO_ROOT_USER` / `SILO_ROOT_PASSWORD` / `SILO_BUCKET` | CAS-хранилище |
| `BACKUP_RESTIC_PASSWORD` | Пароль шифрования restic-репозитория; смена = старые снапшоты нечитаемы |
| `BACKUP_INTERVAL_SECONDS` | Интервал цикла копирования (86400 = сутки) |
| `LOG_LEVEL`, `LOG_MAX_SIZE`, `LOG_MAX_FILE` | Логи приложений и ротация логов контейнеров (HLD §8.3) |
| `KB_PUBLIC_URL` | Публичный адрес стенда (`http://IP` или `https://домен`): redirectUris realm, CORS api, адрес Keycloak в SPA (build-arg nginx). Пусто — локальный стенд. Смена после первого импорта realm — только `down -v` или правка в консоли Keycloak |
| `KC_HOSTNAME_URL` | Адрес Keycloak (issuer): для `KB_PUBLIC_URL=https://домен` — `https://домен/auth` (TLS за nginx, порт 8080 закрыт); для `http://IP` — `http://IP:8080` |
| `VITE_APP_BASE` | База приложения (подпуть): `/know` → приложение на `http://IP/know/` (nginx отдаёт SPA из подпути, redirect_uri матчится `${KB_PUBLIC_URL}/*`). Пусто — корень. Смена → `docker compose build nginx` |
| `KB_PKCE_METHOD` | PKCE-метод клиента `kb-spa` в realm (дефолт `S256`). На http-стендах SPA не имеет `crypto.subtle` (нет secure context) и шлёт `plain` — задать `KB_PKCE_METHOD=plain`; после включения TLS вернуть `S256`. Смена → `down -v` (переимпорт realm) |

### 2.3. Запуск

```bash
cd deploy
docker compose up -d          # сборка api/worker/nginx + старт всех сервисов
docker compose ps             # все сервисы healthy/exit 0
```

При старте автоматически:
1. `postgres`: init-скрипт создаёт БД `keycloak`; `pgbackrest.sh` (фоновый цикл
   в контейнере postgres) создаёт stanza `kb` и ведёт базовые копии;
2. `keycloak`: импорт realm `kb` из `keycloak/realm-kb-test.json` (тестовый realm
   с сид-пользователями, состав — §7). **Для внедрения** — импорт рабочего realm
   без тестовых УЗ: подготовить отдельный JSON (без сид-пользователей,
   свои секреты клиентов) и смонтировать его вместо `realm-kb-test.json`;
   realm не переимпортируется, если уже существует в БД (изменение паролей —
   `down -v` или kcadm `set-password`);
3. `api`: `alembic upgrade head` → uvicorn;
4. `silo-init`: создание бакета CAS;
5. `backup`: ждёт первый успешный pgBackRest-цикл → restic-снапшот silo →
   textfile `/backups/prometheus/backup_state.prom` (скрейпится node-exporter).

Проверка: `http://localhost/healthz` (через nginx) → `{"status":"ok"}`;
UI — `http://localhost/` (или `http://localhost/know/` при `VITE_APP_BASE=/know`);
API-документация — `http://localhost:8001/api/v1/docs`
(NFR-021). Первый СА системы заводится через Keycloak-консоль и назначается
группой СА в realm (13.2) — либо используются учётные записи realm-импорта.

### 2.4. Синхронизация учётных записей (первый вход)

Список пользователей тянется из Keycloak задачей `keycloak.sync` (расписание —
5 минут, LLD §9). Для немедленной синхронизации после первого старта:

```bash
docker compose exec api python -c "from app.worker.tasks import keycloak_sync; keycloak_sync()"
```

## 3. Мониторинг и алертинг (NFR-019)

- Prometheus: `http://localhost:9090` — targets (`Status → Targets`), алерты
  (`Alerts`). 15 правил в 5 группах: availability (6 probe-алертов + ServiceDown),
  queues (3), app (3), disks (1), backups (2) — `deploy/prometheus/alerts.yml`.
- Пробы (`blackbox-exporter`): realm-эндпоинт Keycloak, Gotenberg `/health`,
  Silo `/minio/health/live`, nginx `/healthz`, Valkey (tcp_connect).
- Очереди: `kb_queue_depth` / `kb_queue_age_seconds` / `kb_queue_error_ratio`
  (worker-экспозер :9808, источник — `system_tasks`, LLD §9); API: `kb_api_*`
  (счётчики/латентность по нормализованным маршрутам).
- Бэкапы: `kb_backup_freshness_seconds`, `kb_backup_failed` (textfile через
  node-exporter). Алерты: BackupStale (> 25 ч), BackupFailed.
- **Канал алертинга** — email СА через Alertmanager; в MVP SMTP не настроен,
  приёмник-заглушка (US-040 A1). Настройка при внедрении:
  `deploy/prometheus/alertmanager.yml` → блок `email_configs` (SMTP-сервер
  организации), затем `docker compose restart alertmanager`.

## 4. Резервное копирование (NFR-012) и восстановление (NFR-013)

### 4.1. Что копируется

- **PostgreSQL** (БД `kb` + `keycloak` — один кластер, HLD §8.2): pgBackRest,
  stanza `kb`. WAL-архив непрерывен (`archive_command` → том `backups`,
  `archive_timeout=60s`, RPO ≤ 1 ч); базовые копии — цикл в `pgbackrest.sh`:
  полная по воскресеньям, инкремент пн–сб, интервал `BACKUP_INTERVAL_SECONDS`.
- **Файловое хранилище (silo)**: restic-репозиторий `/backups/restic` (том
  `backups`); снапшот сразу после успешной pgBackRest-копии (согласование по
  времени — единая точка восстановления); CAS-объекты неизменяемы (ключ sha256).
- Координация: postgres-контейнер пишет маркеры `/backups/status/pgbackrest.done`
  / `.failed`; контейнер `backup` ждёт свежий маркер → restic → textfile.
- Политики: pgBackRest `repo1-retention-full=2`; restic `--keep-daily 7
  --keep-weekly 8`.

### 4.2. Проверка состояния

```bash
docker compose exec postgres pgbackrest --stanza=kb info   # копии и их возраст
docker compose exec backup restic snapshots                 # снапшоты silo
curl -s http://localhost:9100/metrics | grep kb_backup      # метрики свежести
```

### 4.3. Восстановление БД (pgBackRest, RTO-процедура)

Восстановление выполняется в остановленный кластер (postgres down):

```bash
docker compose stop api worker backup postgres
# pgdata том остаётся; pgbackrest restore пишет поверх (--delta) из последней копии
docker compose run --rm --entrypoint bash postgres -c "\
  pgbackrest --stanza=kb --delta --target-action=promote restore"
docker compose up -d postgres   # кластер стартует и накатывает WAL до последнего сегмента
docker compose up -d api worker backup
```

- Восстановление на момент времени (PITR): добавить `--target="2026-11-09 12:00:00+03"`.
- После восстановления проверить `pgbackrest --stanza=kb info` (статус ok),
  залогиниться в UI, сверить количество материалов.

### 4.4. Восстановление файлов (restic)

```bash
docker compose run --rm --entrypoint bash backup -c "\
  restic restore latest --target /tmp/restore"
# затем сверить и залить в том silo (объекты неизменяемы — просто докопировать):
docker compose run --rm --entrypoint bash backup -c "\
  restic restore latest --target /silo-data --overwrite if-changed"
```

### 4.5. Полная потеря узла (RTO ≤ 4 ч)

1. Поднять Docker + скопировать `deploy/` (compose, .env, конфиги) и том `backups`
   (или его внешнюю копию — регламент вывоза копий определяется при внедрении).
2. `docker compose up -d` (образы пересоберутся; realm-импорт пропустится — БД
   keycloak восстановится из pgBackRest-копии).
3. Выполнить §4.3 и §4.4 из восстановленного тома `backups`.
4. Проверка приёмки восстановления: вход пользователей, поиск, скачивание файла.

Процедура отрабатывается при внедрении (NFR-013, шаг [6]) с фиксацией фактического RTO.

## 5. TLS (FR-149) — настройка при внедрении

Схема для доменного имени (проверена на этапе 11: 31/31 сценариев поверх TLS).
Итог: Keycloak для браузера доступен только через nginx по `/auth` (порт 8080
наружу закрыт), issuer = `https://домен/auth/realms/kb`.

1. DNS: A-запись домена → IP сервера.
2. `.env` — задать **до первого `up`** (realm-импорт подставляет их в
   redirectUris один раз; смена позже — `down -v` или консоль Keycloak):
   ```ini
   KB_PUBLIC_URL=https://merch-vibe.ru
   KC_HOSTNAME_URL=https://merch-vibe.ru/auth
   KB_PKCE_METHOD=S256
   ```
   (`KB_PKCE_METHOD` — если стенд жил на http с `plain`: HTTPS вернёт secure
   context, SPA снова шлёт S256 — политика realm должна совпасть; переимпорт
   realm — `down -v` перед `up`.)
3. Сертификат. Рабочий вариант — Let's Encrypt; nginx принимает и самоподписанный
   (в `certs/` уже лежит placeholder, генерируемый `tls-fallback.sh` при старте).
   Первый выпуск (webroot через работающий nginx — nginx уже должен быть запущен):
   ```bash
   sudo apt install certbot
   sudo certbot certonly --webroot -w deploy/nginx/acme -d merch-vibe.ru \
     --deploy-hook "cp /etc/letsencrypt/live/merch-vibe.ru/fullchain.pem deploy/nginx/certs/kb.crt && cp /etc/letsencrypt/live/merch-vibe.ru/privkey.pem deploy/nginx/certs/kb.key && cd deploy && docker compose exec nginx nginx -s reload"
   # сертификаты: /etc/letsencrypt/live/merch-vibe.ru/{fullchain.pem,privkey.pem}
   # (альтернатива для стендов без домена — самоподписанный:
   #  openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout kb.key -out kb.crt
   #  -subj "/CN=merch-vibe.ru" -addext "subjectAltName=DNS:merch-vibe.ru")
   ```
   Сами файлы `deploy/nginx/certs/kb.{crt,key}` — в .gitignore, только на сервере.
4. `docker compose up -d --build` — SPA получит адрес Keycloak автоматически
   (build-arg nginx из `KB_PUBLIC_URL` → VITE_KC_BASE = `https://домен/auth/realms/kb`).
5. Обновление сертификата (раз в ~60 дней, автоматически deploy-hook'ом из п. 3;
   при webroot nginx не останавливается):
   ```bash
   sudo certbot renew --dry-run   # проверка автопродления
   ```

### 5.1. Порядок первого выпуска сертификата (webroot требует работающий nginx)

На чистом сервере nginx стартует с self-signed placeholder (fallback) — HTTP
работает сразу. Затем webroot-выпуск п. 3, deploy-hook копирует сертификаты в
`certs/` и перезагружает nginx — TLS сразу с боевым сертификатом. Контейнеру
доступен каталог ACME (`deploy/nginx/acme` → `/var/www/certbot` в nginx).

После перехода на TLS закрыть порт 8080 в панели провайдера (Keycloak —
только за nginx по `/auth`); фаервол панели, не ufw — Docker его обходит.
Из http-стенда (PKCE plain) переход = `down -v` + пересев `seed_demo.py`
(realm импортируется один раз).

## 6. Обслуживание

- **Логи**: `docker compose logs api|worker|postgres` (json-file, ротация — §2.2).
- **Застой очередей**: при росте `kb_queue_age_seconds` — известная проблема
  зависшего Celery-child: `docker compose restart worker`.
- **Плановые задачи** (LLD §9, beat встроен в worker): integrity_check еженедельно,
  fts_rebuild еженедельно, cas_gc/cas_reconcile — еженедельно/ежедневно.
- **Обновление версии**: `git pull`, `docker compose build api worker nginx`,
  `docker compose up -d` (миграции применяются при старте api автоматически).
- **Чистый перезапуск с потерей данных**: `docker compose down -v` (внимание:
  удаляет тома, включая `backups` — выгрузить копии заранее).

## 7. Демонстрационные данные стенда (тестовый realm)

Полный сброс контента и пересев демо-набора (пользователи, группы с иерархией,
материалы во всех статусах, мастер-подчинённая цепочка):

```bash
cd deploy
# 1. Очистить silo (CAS-объекты) и БД (контентные таблицы; роли/настройки/переходы сохраняются)
docker compose run --rm --entrypoint /bin/sh -v "${PWD}/silo-clean.sh:/clean.sh:ro" silo-init /clean.sh
Get-Content cleanup.sql -Raw | docker compose exec -T postgres psql -U kb -d kb
# 1а. После TRUNCATE СА теряет is_super (user_roles пуст) — вернуть напрямую:
docker compose exec -T postgres psql -U kb -d kb -c "INSERT INTO user_roles (user_id, role_id) SELECT u.id, r.id FROM users u, roles r WHERE u.display_name = 'Иван Иванов' AND r.name = 'Системный администратор';"
# 2. Пересеять демо-данные (идемпотентно: сеет недостающее, существующее не трогает)
python seed_demo.py            # --check — только отчёт о состоянии
```

Состав демо-набора: 6 пользователей — 5 в realm JSON (ivanov — СА,
petrov (Рецензент), sidorov (Автор), smirnova (Читатель), kuznetsov
(без роли — проверка оффера выбора роли)) + merch (СА; в realm JSON нет —
создаётся через kcadm при сиде `seed_demo.py`, ASCII-логин для kcadm).
Группы: «Корпоративные регламенты»
(ИТ, Информационная безопасность), «Управление персоналом» (Онбординг,
Администрирование) — со снапшотами прав по ролям. 9 материалов: мастер
«Регламент резервного копирования» (публикация) + 2 подчинённых (адаптация в
Онбординге, перевод ENG в ИТ), остальные — публикации/утверждён/на проверке/
черновик. Пароль всех пользователей — `KB_TEST_PASSWORD` (тестовый realm).
Вход в SPA — по подпути (§2.2 `VITE_APP_BASE`), например `http://IP/know/`.
