# Детальное проектирование (LLD) корпоративной базы знаний

> **Версия:** 0.5 · **Дата:** 09.11.2026 · **Статус:** актуальная редакция (принята; раунд 5 — замечания реализации этапа 11)

## История изменений

| Версия | Дата | Изменения |
|---|---|---|
| 0.5 | 09.11.2026 | Раунд 5 (реализация MVP, этап 11 «НФТ и приёмка»; Приложение А, №33–38): §9 дополнен реализацией метрик (kb_queue_* worker-экспозер :9808, kb_api_* middleware api, окно 24 ч, нормализация маршрутов, 15 правил алертинга, blackbox-пробы) и механикой бэкап-контура (NFR-012: tools-образ postgres:18.6+pgBackRest+restic, WAL-архив RPO ≤ 1 ч, stanza kb = БД kb+keycloak, restic-снапшоты silo с согласованием по времени, маркеры + textfile-свежесть, алерты BackupStale/BackupFailed); №35 — fail-closed интроспекции приведён к §10 (active=false → 401, был KeyError 500); №36–38 — поисковые оптимизации по итогам НТ (NFR-001): фильтр partial на `name % q` + SET LOCAL порога (№36), раскладка предиката/ранжирования по distinct search_lang с константным конфигом + батч-подсветка ts_headline (№37), fastupdate=off (миграция 0010), COUNT без ORDER BY, plan_cache_mode=force_custom_plan, требование лексического разнообразия нагрузочного корпуса (№38); процедуры восстановления — deploy/README.md. Контракты §12 без изменений |
| 0.4 | 09.11.2026 | Раунд 4 (реализация MVP, этап 10 «СА-контур»): §11 — полный перечень кодов действий аудита по факту реализации (type/attribute/dictionary/tag/role/user.*, snapshot.update, user.role_revoke/deactivate) и охват `audit_log` всех админ-use-cases (FR-140); §10 — сверка `keycloak.sync` реактивирует (`enabled=true` → `is_deactivated=false`), пагинация страницами по `KEYCLOAK_SYNC_PAGE`; deploy-требование Admin API Keycloak ≥26.8 (scope `kc-admin-api` + роль `view-users` сервисному аккаунту). Контракты §12 без изменений; синхронные правки других документов не требуются (замечания — механика реализации, не поведение) |
| 0.3 | 09.11.2026 | Раунд 3 (реализация MVP, этапы 7–8; Приложение А, №30–32): частичное совпадение — ILIKE по подстроке как основной механизм [уточнение LLD к §7.3] (trgm-`%` не находит подстроку в длинном названии, FR-114); явный каст `search_lang::regconfig` в запросах/ранжировании/подсветке (§7.3/§7.4 — PG не приводит varchar неявно); точки вставки пересчёта search_tsv в сервисных мутациях (§7.1). Контракты §12 без изменений; синхронные правки других документов не требуются (замечания — механика реализации, не поведение) |
| 0.2 | 09.11.2026 | Документ принят (статус «черновик для ревью» снят; два внутренних раунда ревью — 29 замечаний, Приложение А). Раунд 1 (22 замечания): исправлен SQL-предикат прав (префикс-поиск поддерева, скобки, SA на published/archived, view без права); устранено противоречие «привязка файла только ready» vs конвейер загрузки; пересобран блок /users (без POST, DELETE = деактивация); email-кэш из users.email_cache (16.1-119); дедуп-гонка и FILE_PENDING_SCAN; cas_reconcile учитывает soft-deleted; сид «Язык» отдан шагу [6]; задача fts_rebuild; параметры trgm/gc/short_query в реестр; коды NOT_IMPLEMENTED/PRECONDITION_REQUIRED/FILE_PENDING_SCAN; коды аудита move/copy/master_change/role.delete; ETag = materials.version; UNIQUE material_versions; поля дайджеста и bigserial. Раунд 2 (контрольный, №23–29): /transition-rules и ARCHIVED_SOURCE_RULE_FORBIDDEN; UNIQUE transition_rules (§2.4); слияние тегов (FR-053); file-state для опроса конвейера; ссылка §8.3→§8.2; привязка параметров §2.5 в тексте; email_cache в потоках §10. Синхронно: HLD ред. 1.1 (§5.2), REQUIREMENTS ред. 1.6 (FR-151), CONCEPT ред. 2.17 (16.1-119), SCENARIOS ред. 0.9 (US-040) |
| 0.1 | 08.11.2026 | Первая редакция (черновик для ревью). Шаг [4] плана (CONCEPT.md, раздел 17): модель данных (таблицы, поля, ограничения, индексы, инициализация), механизм проверки прав (SQL-предикат, кэш, инвалидация), жизненный цикл (матрица, валидаторы, побочные эффекты), версионирование (снапшот, diff, ETag), файлы (CAS-ключи silo, конвейер, отдача, сборка мусора), поисковый индекс (FTS-вектор, веса, разбор запроса), уведомления (события, получатели, анти-шум), очереди (имена задач, ретраи), интеграция Keycloak (introspection, сверка), аудит, контракты API (соглашения, ошибки, состав эндпоинтов). Закрыты открытые вопросы HLD §12 (№1–8) |

## 1. Назначение документа и связь с проектом

- Документ выполняет шаг [4] плана (CONCEPT.md, раздел 17): детальное проектирование — конкретная модель данных (таблицы, поля, связи), контракты API, механизм проверки прав, механизм версионирования, поисковый индекс.
- Входные документы: CONCEPT.md (ред. 2.17), REQUIREMENTS.md (ред. 1.6), SCENARIOS.md (ред. 0.9), HLD.md (ред. 1.1). LLD не переопределяет правила концепции и решения HLD, а детализирует их до уровня, достаточного для реализации (шаг [5]).
- Ссылки: (4.1) — разделы концепции; (FR-xxx), (NFR-xxx) — требования; (US-xxx) — сценарии; (16.1-xx) — решения концепции; (HLD, §N) — разделы высокоуровневой архитектуры.
- Решения уровня HLD (стек, состав контейнеров, принципы подсистем) не пересматриваются; уточнения внутрисистемной механики HLD помечаются «[уточнение LLD]» с указанием раздела HLD.
- Охват — только MVP; пост-MVP — только как закладываемые структуры (реестр — 15.3).

## 2. Модель данных

### 2.1. Перечисления (типы PostgreSQL ENUM)

| Тип | Значения | Источник |
|---|---|---|
| material_status | `draft`, `in_review`, `approved`, `published`, `archived` | 7.2, FR-065 |
| permission_code | `view`, `create`, `edit`, `delete`, `review`, `publish`, `archive`, `copy`, `move`, `download`, `manage_permissions` | 8.6, FR-106 |
| attr_value_type | `string`, `number`, `date`, `url`, `dictionary` | 6.1, FR-044 |
| scan_state | `pending_scan`, `scanning`, `ready`, `infected` | HLD §7.3, FR-057/058 |
| pdf_state | `none`, `converting`, `ready_pdf`, `convert_failed` | HLD §7.3, FR-059/060 |
| event_type (уведомления) | `material_sent_to_review`, `material_rejected`, `material_archived`, `child_auto_archived`, `master_changed`, `material_changed_on_review`, `status_changed` (общий), `file_blocked` | 11.1, FR-134 |
| recipient_type | `role`, `fact_author`, `fact_signatory`, `fact_last_editor`, `permission_holder` | 11.2, FR-135 |
| channel | `in_app`, `email` | 11.3 |
| task_state | `queued`, `running`, `done`, `failed` | NFR-014 |
| task_type | `antivirus`, `conversion`, `email`, `digest`, `audit_cleanup`, `inapp_cleanup`, `analytics_rollup`, `cas_gc`, `cas_reconcile`, `keycloak_sync`, `integrity_check`, `fts_rebuild` | HLD §3.2, §6.4, §6.5 |
| service_task_type | `transfer_review_right` | FR-012 |

### 2.2. Таблицы

Ключи: `uuid` — генерируется приложением (UUIDv7 — монотонность для индексов); исключение — `audit_entries.id bigserial` (append-only поток, §11); даты — `timestamptz` (UTC, NFR-018). Ниже — таблицы; состав строк «Поле / Тип / Примечание».

**users** (FR-001, FR-151; минимум ПДн)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| keycloak_id | text UNIQUE NOT NULL | суб/идентификатор из токена |
| display_name | text NOT NULL | из claim токена |
| is_deactivated | boolean NOT NULL DEFAULT false | поддерживается сверкой (§10) |
| is_service | boolean NOT NULL DEFAULT false | сервисная УЗ (FR-013): определяется по типу клиента токена при первом запросе; уведомления не доставляются |
| email_cache | text NULL | `[уточнение LLD]` кэш email для рассылок — 16.1-119: заполняется из claim токена при первом запросе и сверкой (§10); при пустом кэше — фолбэк Admin API (§8.2); адрес истины — Keycloak (FR-151) |
| created_at / updated_at | timestamptz | |

**roles** (шаблоны ролей, FR-008)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| name | text UNIQUE NOT NULL | |
| is_virtual_all_users | boolean DEFAULT false | роль «Все пользователи» (FR-009) — виртуальная: снапшоты с `role_id = NULL, all_users = true` действуют для всех аутентифицированных |
| created_at | timestamptz | |

**role_permissions** (состав шаблона, FR-008): `role_id FK`, `permission (permission_code)`, PK (role_id, permission).

**user_roles** (FR-007, FR-010): `user_id FK`, `role_id FK`, PK (user_id, role_id) — совмещение нескольких ролей = несколько записей.

**permission_snapshots** (снапшот, FR-100, 8.1)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| object_type | ENUM(`group`, `material`) | |
| object_id | uuid | без FK на таблицы объектов (единый полиморфный доступ); каскадное удаление — сервисом |
| role_id | uuid NULL FK roles | NULL → виртуальная роль «Все пользователи» |
| created_by | uuid FK users | |
| created_at | timestamptz | |

**permission_entries**: `snapshot_id FK`, `permission (permission_code)`, `state ENUM('allow','deny')`, PK (snapshot_id, permission). Отсутствие записи = «не задано» (8.3).

**groups** (4.1, FR-015–023)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| name | text NOT NULL (≤ 255, параметр) | |
| normalized_name | text NOT NULL | `lower(trim(name))`; «е»/«ё» не отождествляются — `lower()` не меняет «ё» (16.1-54) |
| parent_id | uuid NULL FK groups | NULL — корневая |
| path | text NOT NULL | материализованный путь: `/id1/id2/…/idN/`; сегменты — id групп; глубина = число сегментов; перенос групп не предусмотрен (FR-023) → path неизменен после создания |
| is_deleted | boolean DEFAULT false | soft-delete ветки (FR-019) |
| deleted_at | timestamptz NULL | |
| created_at | timestamptz | |

Пустая группа удаляется физически (DELETE записи, FR-018); soft-deleted — только непустые ветки.

**material_types** (6.1): `id uuid PK`, `name text UNIQUE`, `created_at`. Удаление типа — только при отсутствии неудалённых материалов (FR-050): физический DELETE + запрет в сервисе.

**attributes** (глобальный пул, 6.1, FR-044/045)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| name | text UNIQUE NOT NULL | |
| value_type | attr_value_type NOT NULL | неизменяемо (FR-045) |
| is_multivalue | boolean NOT NULL | только для string/url/dictionary (FR-044); неизменяемо |
| is_required | boolean DEFAULT false | изменяемо; действует для последующих сохранений (FR-045) |
| display_order | int | порядок в карточке |
| dictionary_id | uuid NULL FK dictionaries | NOT NULL при value_type='dictionary' |
| created_at | timestamptz | |

**dictionaries** (FR-047): `id uuid PK`, `name text UNIQUE`.
**dictionary_values**: `id uuid PK`, `dictionary_id FK`, `value text NOT NULL`; UNIQUE (dictionary_id, value). Удаление значения — запрет при использовании неудалёнными материалами (FR-047), проверка сервисом.

**attribute_type_bindings** (FR-044): `type_id FK`, `attribute_id FK`, PK (type_id, attribute_id); лимит 50 атрибутов на тип — параметр, проверка сервисом. Исключение атрибута из типа — DELETE записи без удаления значений (FR-051).

**materials** (4.2, FR-024–028)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| group_id | uuid FK groups NOT NULL | ровно одна группа (FR-024) |
| name | text NOT NULL (≤ 255) | |
| normalized_name | text NOT NULL | `lower(trim(name))` — уникальность в группе |
| type_id | uuid FK material_types | |
| status | material_status DEFAULT 'draft' | |
| master_id | uuid NULL FK materials | NULL — мастер/самостоятельный; один уровень связи (FR-032) |
| author_id | uuid FK users | авторство — видимость, не права (FR-014) |
| signatory_id | uuid NULL FK users; signatory_at | фиксируются при переходе в «Утверждён» (FR-068); очищаются при снятии (FR-082/084) |
| last_editor_id | uuid FK users | |
| current_file_id | uuid NULL FK file_objects | NULL — «пустышка»; отдача/переходы — только с FileObject в `ready` (5.2 HLD, §6.4) |
| text_content | text NULL | Markdown — канонический формат (16.1-4) |
| text_out_of_sync | boolean DEFAULT false | признак рассинхронизации с файлом (FR-030) |
| version | int NOT NULL DEFAULT 1 | оптимистичная блокировка + ETag (FR-093–095) |
| published_at, archived_at, created_at, updated_at | timestamptz | |
| is_deleted, deleted_at | boolean, timestamptz | soft-delete (FR-090) |

Пользователь публикации (FR-086) — отдельной колонки нет; извлекается из `status_log.user_id` последней записи с `to_status='published'` (§4.1).

**material_versions** (12.2, FR-144–148) — §5.

**file_objects** (NFR-010, FR-057) — §6.

**attribute_values** (6.1, FR-051)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| material_id FK, attribute_id FK | | |
| value_string | text NULL | value_type='string' |
| value_number | numeric NULL | 'number' |
| value_date | timestamptz NULL | 'date' |
| value_url | text NULL | 'url' (валидация URL) |
| dictionary_value_id | uuid NULL FK dictionary_values | 'dictionary' |

Ровно одно из пяти значений NOT NULL — CHECK; соответствие типу атрибута — сервис (однотипность колонок исключает смешение). Многозначность — несколько строк. «Осиротевшие» значения (атрибут исключён из типа) — остаются, читаются, не редактируются, участвуют в поиске (FR-051, 16.1-115).

**tags** (6.4): `id uuid PK`, `name text UNIQUE`. **material_tags**: `material_id FK`, `tag_id FK`, PK (material_id, tag_id); лимит 20 — параметр, проверка сервисом. Слияние тегов (FR-053): UPDATE `material_tags.tag_id` на целевой тег в одной транзакции с переименованием/удалением исходного; аудит `tag.*`.

**comments** (7.6, FR-096–098): `id uuid PK`, `material_id FK`, `author_id FK users`, `text text NOT NULL`, `created_at`. Без UPDATE/DELETE (неизменяемость).

**transition_rules** (7.4, FR-070–074)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| from_status | material_status NULL | NULL = «*» (любой статус, кроме «Архива»: правило с `from_status='archived'` запрещено — FR-073, §2.6) |
| to_status | material_status NOT NULL | |
| is_protected | boolean DEFAULT false | защищённые: нельзя удалить (FR-073) |
| created_at | timestamptz | |

UNIQUE (from_status, to_status) — одна строка на переход; `from_status='archived'` отсекается частичным индексом `WHERE from_status <> 'archived' OR from_status IS NULL` + проверкой сервиса (`ARCHIVED_SOURCE_RULE_FORBIDDEN`, §12.2).

**transition_rule_permissions**: `rule_id FK`, `permission (permission_code)`, PK (rule_id, permission) — несколько прав, достаточно любого (FR-070). Удаление перехода — DELETE строки (FR-074: статусы существующих материалов не меняются).

**status_log** (FR-075): `id uuid PK`, `material_id FK`, `from_status NULL`, `to_status`, `user_id FK`, `created_at`. Дополнение при каждом переходе, включая каскадную архивацию (каждый подчинённый — отдельная запись).

**notifications** (11.3, FR-136–138; §8)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| recipient_id | uuid FK users | инициатор исключён (FR-138), сервисная УЗ — не доставляется (FR-013) |
| event_type | event_type | |
| material_id | uuid NULL FK materials | |
| channel | channel | in_app строка; email — задача очереди |
| dedup_key | text NOT NULL | анти-шум: `<event_type>:<material_id>:<recipient>` в окне (§8.2) |
| email_state | task_state NULL | состояние email-доставки (если канал активен) |
| read_at | timestamptz NULL | индивидуальное прочтение (FR-137) |
| included_in_digest_at | timestamptz NULL | отметка «вошло в дайджест» (§8.2, 11.3) |
| created_at | timestamptz | срок хранения ≥ аудита (FR-137) |

**notification_events** (§8.1): `id uuid PK`, `event_type`, `material_id NULL`, `initiator_user_id NULL`, `payload jsonb NULL`, `created_at`, `processed boolean DEFAULT false` — публикуются в транзакции изменения материала; обрабатываются диспетчером.

**trigger_configs** (11.2, FR-135)

| Поле | Тип | Примечание |
|---|---|---|
| id | uuid PK | |
| event_type | event_type UNIQUE | одна конфигурация на событие |
| enabled | boolean | общий «изменение статуса» — false (16.1-89) |
| recipients | jsonb | массив `{type: recipient_type, role_id?: uuid, permission?: permission_code}` |

**audit_entries** (12.1, FR-140–143) — §11.

**search_events / search_opens / search_analytics** (9.9, FR-127) — §7.6.

**system_tasks** (NFR-014; §9): `id uuid PK`, `task_type`, `object_type NULL`, `object_id NULL`, `state task_state`, `attempts int`, `last_error text NULL`, `scheduled_at`, `started_at NULL`, `finished_at NULL`. Источник истины по состояниям задач (HLD, §3.2); брокер — транспорт.

**service_tasks** (FR-012): `id uuid PK`, `task_type service_task_type`, `payload jsonb` (группа, право, деактивированный пользователь), `state task_state`, `created_at`, `closed_at NULL`. Незакрываема, пока право не передано (US-004).

**system_settings** (NFR-020): `key text PK`, `value jsonb NOT NULL`, `description text`, `updated_at`. Состав — §2.5.

### 2.3. Ограничения целостности

**Уникальность названий** (FR-017, FR-027; удалённые не участвуют — 16.1-22): частичные уникальные индексы:

```sql
CREATE UNIQUE INDEX uq_materials_name_in_group
  ON materials (group_id, normalized_name) WHERE is_deleted = false;
CREATE UNIQUE INDEX uq_groups_name_among_siblings
  ON groups (COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), normalized_name)
  WHERE is_deleted = false;
```

**CHECK-ограничения:**

| Ограничение | Реализация | Источник |
|---|---|---|
| `master_id <> id` | CHECK | FR-032 |
| Мастер без собственного мастера | CHECK `master_id IS NULL OR NOT EXISTS (SELECT 1 FROM materials m WHERE m.id = materials.master_id AND m.master_id IS NOT NULL)` — проверяется триггером на вставку/обновление (CHECK с подзапросом недопустим) | 4.4 |
| Даты согласованы | `published_at` только в «Публикации» и т.п. — сервис + периодическая сверка целостности (§9) | FR-086 |
| Атрибут: значение соответствует типу | ровно одна колонка значения NOT NULL — CHECK | 6.1 |
| Файл материала проверен | при **отдаче** (§6.4) и переходах (валидатор 3 §4.1) используется только FileObject со `scan_state='ready'`; FK невозможен (состояние меняется). При загрузке привязка создаётся сразу (§6.2), до завершения проверки; отдача/переходы до `ready` отсекаются условием отдачи/валидатором | 5.2 HLD, FR-058 |

**Инварианты уровня сервиса** (в одной транзакции с изменением; перечислены по 4.4/4.5, 7.9):

1. Циклы `master_id` запрещены: новый мастер не находится в поддереве подчинённых (тривиально — один уровень: новый мастер ≠ сам материал и не имеет `master_id`).
2. Материал с неудалёнными подчинёнными (`master_id = материал`): не получает `master_id`, не перемещается, не удаляется (FR-032, FR-037, FR-040).
3. Удаление ветки группы запрещено при мастере с неудалёнными подчинёнными вне ветки (FR-020): проверка `path` подчинённых против `path` ветки.
4. Инварианты «использования» — только по неудалённым материалам (FR-091): подчинённые, значения атрибутов, назначения типов, использования тегов и значений справочников.
5. Смена мастера/отвязка: статусы по FR-036; новый мастер виден пользователю (16.1-96).

### 2.4. Индексы

| Таблица | Индекс | Назначение |
|---|---|---|
| groups | B-tree `parent_id`; GIN trgm `name` (`gin_trgm_ops`) | дерево; поиск групп (§7.5) |
| groups | B-tree `path` (prefix-поиск LIKE '/id/%' для поддеревьев) | наследование прав, ветки |
| materials | B-tree `(group_id, status)`, `master_id`, `author_id`, `type_id`, `status`, `updated_at DESC` | списки, фильтры, разделы |
| materials | UNIQUE `(group_id, normalized_name) WHERE is_deleted=false` | FR-027 |
| material_versions | UNIQUE `(material_id, number)` | §5.1 |
| transition_rules | UNIQUE `(from_status, to_status)`; частичный `WHERE from_status IS NULL OR from_status <> 'archived'` (FR-073) | §2.2 |
| materials | GIN `search_tsv`; GIN trgm `name`, `text_content` | поиск (§7) |
| file_objects | UNIQUE `sha256` | дедупликация (NFR-010) |
| attribute_values | B-tree `(material_id, attribute_id)`; `(attribute_id, value_number)`, `(attribute_id, value_date)` | фильтры по атрибутам (FR-116) |
| permission_snapshots | B-tree `(object_type, object_id)`, `role_id` | предикат прав (§3) |
| status_log, comments, audit_entries, notifications | B-tree по объекту/получателю/дате | ленты, журнал, очистка по возрасту |
| system_tasks | B-tree `(task_type, state)` | мониторинг очередей (NFR-019) |

### 2.5. Реестр параметров (system_settings, значения по умолчанию)

Раздел 5 REQUIREMENTS + механические параметры уровня LLD `[уточнение LLD]`:

| Ключ | По умолчанию | Источник |
|---|---|---|
| `file_max_size_mb` | 100 | FR-031 |
| `mime_extra` | `[]` (базовый набор — §6.2, в коде константой с предпросмотром по FR-055) | FR-056 |
| `fts_languages` | `["russian","english"]` | FR-122 |
| `master_change_criterion` | `"content"` (\| `"any"`) | FR-038 |
| `content_downgrade_params` | `["file","text"]` | FR-084 |
| `audit_retention_days` | NULL (определяется при внедрении; NULL — очистка не выполняется) | FR-141 |
| `digest_interval_minutes` | NULL (email-дайджест отключён до настройки) | FR-138 |
| `smtp_*` (host, port, from, TLS) | не настроено → email-канал и алертинг отключены (US-040 A1) | FR-136, NFR-019 |
| `page_size` | 50 | FR-121 |
| `tags_max` | 20 | FR-052 |
| `attributes_max_per_type` | 50 | FR-044 |
| `name_max_len` | 255 | FR-017, FR-027 |
| `anti_noise_window_minutes` | 10 `[уточнение LLD]` | 11.3 |
| `analytics_raw_retention_days` | 180 `[уточнение LLD]` | 9.9 |
| `keycloak_sync_interval_minutes` | 5 `[уточнение LLD]` | 16.1-118 |
| `trgm_similarity_threshold` | 0.3 `[уточнение LLD]` | FR-113, §7.3 |
| `cas_gc_delay_hours` | 24 `[уточнение LLD]` | §6.5 |
| `short_query_min_len` | 3 `[уточнение LLD]` | ILIKE-фолбэк коротких запросов, §7.3 |

Параметры Keycloak (политики паролей, блокировка перебора, TTL access-токена 15 мин, SSO Session Idle 8 ч) — консоль Keycloak, не реестр (US-048).

### 2.6. Инициализационные данные (сид при первом старте миграции)

| Объект | Состав | Источник |
|---|---|---|
| Каталог прав | 11 значений permission_code | FR-106 |
| Статусы | 5 значений material_status | FR-065 |
| Шаблоны ролей | Читатель: view; Автор: view, create, edit, delete; Рецензент: view, review; Публикатор: view, publish, archive; Системный администратор — без снапшотов (суперпользователь по флагу УЗ/настройке, FR-104) | 5.2 |
| Роль «Все пользователи» | виртуальная (`is_virtual_all_users=true`) | FR-009 |
| Матрица переходов | `draft→in_review`: edit; `in_review→approved`: review; `in_review→draft`: review, edit; `approved→draft`: review; `approved→published`: publish; `*→archived` (from NULL; правила с `from_status='archived'` запрещены — FR-073, код `ARCHIVED_SOURCE_RULE_FORBIDDEN` §12.2): archive; is_protected: `approved→published`, `*→archived`, отсечение исходящих из «Архива» — логика валидатора (защищённое свойство статуса) | FR-071, FR-073 |
| Триггеры уведомлений | `material_sent_to_review` → permission_holder(review); `material_rejected` → fact_author; `material_changed_on_review` → fact_author + permission_holder(review); `master_changed` → fact_author, fact_signatory (подчинённых); `child_auto_archived` → fact_author, fact_signatory (подчинённого); `material_archived` → fact_author, fact_signatory; `status_changed` → disabled | FR-135, 16.1-116 |
| Атрибут «Язык» | справочник, однозначный; значения словаря заводит СА — стартовый состав не фиксируется LLD (шаг [6], FR-046, §14 вопрос 2); атрибут связывается с типами материалов регламентом внедрения | FR-046, 16.1-98 |
| Типы материалов | не создаются (заводит СА) | 6.1 |

## 3. Механизм проверки прав (8, FR-099–109; HLD §12 №3)

### 3.1. Хранение и сбор правил

Снапшоты: `permission_snapshots` + `permission_entries` (§2.2). Эффективное право пользователя на объект вычисляется по правилам 8.5 из всех снапшотов ролей пользователя, найденных в цепочке «материал → группа → … → корневая» (FR-101).

### 3.2. SQL-предикат

Базовая функция видимости материала (inline-CTE в запросах списков/поиска; для одиночных объектов — та же логика через функцию `can(user, permission, material)`; `has_right(eff, p)` — свёртка: true, если в `eff` для права `p` есть `has_allow` и нет `has_deny`):

```sql
WITH user_roles AS (
  SELECT role_id FROM user_roles ur WHERE ur.user_id = :uid
  UNION ALL SELECT NULL WHERE EXISTS (SELECT 1 FROM roles r
      WHERE r.is_virtual_all_users)          -- «Все пользователи», FR-009
),
chain AS (                                   -- материал + все вышестоящие группы
  SELECT :mid AS oid, 'material' AS otype
  UNION ALL
  SELECT g.id, 'group' FROM groups g
  WHERE (SELECT path FROM materials m JOIN groups g2 ON g2.id = m.group_id WHERE m.id = :mid)
        LIKE g.path || '%'                   -- путь группы — префикс пути группы материала
    AND g.is_deleted = false
),
eff AS (
  SELECT pe.permission,
         bool_or(pe.state = 'deny')  AS has_deny,
         bool_or(pe.state = 'allow') AS has_allow
  FROM permission_snapshots ps
  JOIN permission_entries pe ON pe.snapshot_id = ps.id
  JOIN chain c ON ps.object_type::text = c.otype AND ps.object_id = c.oid
  WHERE ps.role_id IN (SELECT role_id FROM user_roles) OR ps.role_id IS NULL
  GROUP BY pe.permission
)
SELECT ... WHERE
  (
    (status IN ('draft','in_review','approved')
       AND (:is_author OR :is_super OR EXISTS (SELECT 1 FROM eff WHERE permission IN
          ('edit','delete','review','publish','archive') AND has_allow AND NOT has_deny)))
  OR
    (status IN ('published','archived')
       AND (:is_super OR EXISTS (SELECT 1 FROM eff WHERE permission='view' AND has_allow AND NOT has_deny)))
  )
  AND ( :permission = 'view'                -- просмотр: достаточно видимости (ветки статусов выше, FR-066)
     OR :is_super
     OR has_right(eff, :permission) );      -- иное действие — право, FR-102
```

Правила: любой явный `deny` в цепочке побеждает (FR-102); отсутствие правил — запрет; суперпользователь — в обход и статуса, и права (FR-104: флаг сессии, вычисляемый из принадлежности к шаблону «Системный администратор»). Хвостовая проверка: `view` не требует отдельного правила — просмотр уже обеспечен ветками видимости (участник процесса без `view` видит черновик/процесс — FR-066; для published/archived видимость даёт `view`); все прочие действия (скачивание, правка, переход) — только по правам (FR-102); в частности, `download` на published/archived требует и видимости (`view` в ветке статуса), и права `download`. Суперпользователь — в обход хвоста. Для групп: право `view` на группу — группа с содержимым; иначе — только путь навигации (FR-103: отдельный запрос видимости групп).

### 3.3. Кэш и инвалидация

- **Кэш в памяти каждого процесса api**: снапшоты (object → entries), дерево групп (path, parent), memberships (user → roles), флаг суперпользователя. При нагрузке 100 пользователей вычисление предиката укладывается в целевые отклики и без кэша (HLD §10); кэш ускоряет списки.
- **Инвалидация**: после commit операций изменения прав/ролей/групп api выполняет `NOTIFY rights_invalidate`; все процессы api подписаны `LISTEN rights_invalidate` и сбрасывают локальный кэш (межпроцессная согласованность внутри одного экземпляра — HLD §6.2 [уточнение LLD: NOTIFY/LISTEN вместо событий в памяти — покрытие нескольких Uvicorn-воркеров]).
- **Подстраховка**: TTL записи кэша 60 с. Кэш не применяется для переходов жизненного цикла и мутаций — только для чтения списков/поиска.

### 3.4. Служебные разделы

- «Мои материалы»: `author_id = :uid AND is_deleted = false` — без предиката прав на группу (FR-123).
- «На проверке»: `status = 'in_review' AND is_deleted = false` + право `review` по предикату §3.2 (FR-124).
- «Архив»: предикат прав + `status = 'archived'` (FR-125, FR-088).
- Служебный раздел СА (удалённые объекты): `is_deleted = true`, только СА (FR-021, FR-090).

## 4. Жизненный цикл: матрица, валидаторы, побочные эффекты (7, FR-065–095)

### 4.1. Механизм перехода

Реализация — сервис `LifecycleService.transition(material, to_status, actor, if_match, confirm_cascade=False)`:

1. **Оптимистичная блокировка** (FR-093, FR-094, FR-095): `UPDATE materials SET ... WHERE id = :id AND version = :expected` — 0 строк → `412` (или повторное чтение для проверки «статус уже изменён»). Все переходы и правки — через проверку версии.
2. **Поиск правила матрицы**: строка `transition_rules` (from_status = текущий, to_status = целевой) либо `from_status IS NULL` («*»); правила кэшируются (§3.3). Правило не найдено → `409 TRANSITION_NOT_ALLOWED`. Правило без прав → доступно только СА (FR-072). Права перехода — достаточно любого из `transition_rule_permissions` (FR-070). Защищённые свойства (FR-073): `approved→published` и `*→archived` — is_protected (нельзя удалить); исходящие из `archived` — запрещены логикой (нет правил; проверка в валидаторе 1).
3. **Цепочка валидаторов** (регистрируемый список, FR-077; порядок фиксирован):
   1. Права перехода (шаг 2).
   2. Наличие файла: для `in_review`, `approved`, `published` — `current_file_id IS NOT NULL` (FR-028, FR-076); `→ archived` — без файла.
   3. Антивирус: `file_objects.scan_state = 'ready'` (FR-058; US-015 A1 — файл отсутствует или не прошёл проверку: переход отклоняется).
   4. Актуальность версии — шаг 1.
   5. Мастер-зависимости: подчинённый не публикуется раньше мастера (FR-042); мастер с подчинёнными в «Публикации» не меняет статус, кроме «→ Архив» (FR-041); правка контента такого мастера блокируется тем же валидатором (§4.3).
   6. Каскадная архивация: при «→ archived» мастера с неудалёнными подчинёнными и `confirm_cascade=false` → `409 CASCADE_CONFIRM_REQUIRED` с числом подчинённых (FR-039, US-021 шаги 4–5); при `confirm_cascade=true` — каскад.
4. **Фиксация** (одна транзакция): новый статус; подписант/дата — при `→ approved` (FR-068), очистка — при возвратах в `draft` (FR-082, FR-084); `published_at`/`archived_at` проставляются; пользователь публикации (FR-086) отдельно не хранится — извлекается из `status_log.user_id` последней записи с `to_status='published'` (§2.2); запись `status_log` (FR-075); запись аудита; события уведомлений (§8.1); `version += 1`.

### 4.2. Правки по статусам (FR-084, FR-085, FR-087)

- Правка контента (состав — параметр `content_downgrade_params`: файл, текст) в `published`/`approved` → возврат в `draft`, очистка подписанта; в `in_review` → статус сохраняется, событие `material_changed_on_review` (FR-085); в `archived` → запрещено (403).
- Правка только метаданных (название, тип, атрибуты, теги) — статусы не снимает никогда.
- Правка контента мастера с подчинёнными в «Публикации» — блокировка валидатором 5 (FR-041).

### 4.3. Удаление и копирование

- Удаление (soft-delete): только из `draft`/`in_review` (FR-090); запрет мастеру с неудалёнными подчинёнными (FR-040); фиксация в аудите.
- Копирование (FR-092): новый материал `draft`; содержимое — копия ссылок (текущий файл → `ref_count + 1` на тот же FileObject, текст, тип, атрибуты, теги копируются значениями); имя «<имя> Копия» со счётчиком; `master_id` сохраняется, если мастер не в архиве.

## 5. Версионирование (12.2, FR-144–148; HLD §12 №4)

### 5.1. Снапшот и фиксация версии

`material_versions`: `id uuid PK`, `material_id FK`, `number int` (с 1, уникально в материале), `snapshot jsonb`, `author_id FK`, `created_at`.

Снапшот (состав FR-144): `{"file_id": uuid|null, "text": string|null, "name": string, "type_id": uuid, "attributes": [{attribute_id, values[]}], "tags": [tag_id]}`. Без `master_id` и прав (FR-144).

**Фиксация**: при каждом сохранении материала (контент или метаданные) — сериализация снапшота и сравнение с последней версией (нормализация: значения атрибутов упорядочены, текст как есть); при различии — новая версия с `number = max + 1`. Изменения статусов, прав, подписанта, `master_id` версией не являются (FR-144). Файл: при замене — новый `file_id`; при неизменности — ссылка на прежний FileObject (дедупликация, FR-147).

### 5.2. Сравнение и восстановление

- **Diff соседних версий** (FR-146, 16.1-83): текст — построчный diff (унифицированный, подсветка на клиенте); метаданные — список `{поле, старое, новое}`; файл — признак `file_changed` (`file_id` различается). Эндпоинт: `GET /materials/{id}/versions/{n}/diff` (сравнение с n−1).
- **Восстановление** (FR-148, 16.1-17): `POST /materials/{id}/versions/{n}/restore` — содержимое снапшота n применяется как правка контента: проходят правила §4.2 (в `published`/`approved` — возврат в `draft`, очистка подписанта; для мастера с подчинёнными в «Публикации» — блокировка FR-041); создаётся новая версия; `master_id` не меняется.
- **ETag**: заголовок `ETag: "<version>"` — `materials.version` (счётчик оптимистичной блокировки; меняется при любой мутации, включая смену статуса), не `material_versions.number` (16.1-95/FR-095); мутации требуют `If-Match`, несовпадение → `412`.

## 6. Файлы: CAS, конвейер, отдача (6.2, 6.5, 13.2, FR-055–064, NFR-010; HLD §12 №6)

### 6.1. Ключи CAS в silo

- Bucket: `cas`. Объекты-исходники: ключ `ab/cd/<sha256-hex>` (первые 4 hex-символа — префикс шардирования; `s3://cas/ab/cd/<sha256>` — HLD §6.4). Объекты неизменяемы: PUT с уже существующим ключом и идентичным содержимым идемпотентен.
- PDF-кэш: ключ `pdf/<sha256-hex>` в том же bucket — перезаписываемый объект-кэш (не CAS-объект; зависит от версии конвертера).
- `file_objects`: `id uuid PK`, `sha256 char(64) UNIQUE`, `size bigint`, `mime text` (определён по содержимому, FR-057), `scan_state scan_state`, `pdf_state pdf_state`, `pdf_key text NULL` (= `pdf/<sha256>` при готовности), `ref_count int NOT NULL DEFAULT 0`, `created_at`.

### 6.2. Загрузка и дедупликация

1. api принимает multipart (лимит — nginx + API, параметр `file_max_size_mb`, FR-031); определяет mime по содержимому (магические байты, FR-057), считает sha256 поточно.
2. Поиск FileObject по sha256:
   - **найден** (`scan_state='ready'`): привязка к материалу, `ref_count + 1` (атомарный UPDATE), повторный антивирус не выполняется (FR-057, NFR-010). Найден в состоянии `infected` → `409 FILE_BLOCKED`; в `scanning`/`pending_scan` → `409 FILE_PENDING_SCAN` («повторите позже», §12.2) — привязка невозможна, загрузка не выполняется;
   - **не найден**: S3 PUT `ab/cd/<hex>`, INSERT FileObject (`pending_scan`, `ref_count=1`), задача очереди `files.scan` (§9). Гонка двух одновременных загрузок: уникальность `sha256` — проигравший INSERT повторяет SELECT; если объект к тому моменту уже `ready` — привязка и `ref_count + 1`; иначе — `FILE_PENDING_SCAN`/`FILE_BLOCKED` (повторная попытка — за пользователем). Оба PUT идемпотентны; `ref_count` проигравшего не инкрементируется до фактической привязки.
   - **судьба `ref_count` при `infected`**: привязка так и не создана, счётчик не растёт; объект с `ref_count=0` подлежит GC (§6.5) — infected-объекты с нулевым счётчиком удаляются `cas_gc` по общему правилу отсрочки.
3. Текстовые файлы (mime `text/*` по FR-029 — определяются по содержимому; HTML исключён — автозаполнение не выполняется, 16.1-87): автозаполнение текстового представления при пустом тексте (FR-029, 16.1-110); при непустом — предложение обновления, при отказе — `text_out_of_sync = true` (FR-030, 16.1-112).

### 6.3. Конвейер

```
загрузка → S3 PUT → FileObject(pending_scan) → files.scan ──► [ready]
                                        │                      │ офисный mime (DOCX/XLSX/PPTX)
                                        │                      ▼
                                        │                  files.convert → Gotenberg
                                        │                      → S3 PUT pdf/<hex> → [ready_pdf]
                                        ▼ (infected)
                              уведомление автору/СА (FR-058) + аудит
```

- **Антивирус (заглушка, 16.1-14)**: обработчик `files.scan` в worker; обе реализации интерфейса сканера в worker (заглушка и клиент clamd), переключение параметром конфигурации окружения (HLD §3.2); заглушка всегда отвечает «чисто». Состояния файла: `pending_scan → scanning → ready|infected`.
- **Конвертация**: `files.convert` только для офисных mime; worker читает объект из silo, вызывает Gotenberg (`POST /forms/libreoffice/convert`), результат — S3 PUT `pdf/<hex>`, `pdf_state='ready_pdf'`. Ошибка → `convert_failed`, скачивание доступно, материал не блокируется (FR-060); ошибка — в логах и `system_tasks.last_error`. Повторная конвертация — только при замене файла (новый FileObject — FR-059).
- Состояния `scan_state`/`pdf_state` обновляются задачами в БД (источник истины — NFR-014); клиент опрашивает `GET /materials/{id}/file-state` (§12.3) — состояния читаются из `file_objects`, без обращения к silo.

### 6.4. Отдача клиенту

- Решение `[уточнение LLD]` (HLD §6.4 допускал варианты): **api-стриминг** — `GET /api/v1/materials/{id}/file` проверяет права и состояние, читает объект из silo (S3 GET) и стримит клиенту; видео/аудио — Range: api транслирует заголовок `Range` в параметр Range S3 GET и возвращает `206 Partial Content` (FR-062). Единая точка авторизации, браузер к silo не обращается.
- PDF-предпросмотр: `GET /api/v1/materials/{id}/pdf` — из `pdf/<hex>`.
- Скачивание текстового представления: `GET /api/v1/materials/{id}/text.md` — право `download` (FR-107, 16.1-108).
- Права (FR-067): предпросмотр — `view`/участие в процессе; скачивание файла и .md — `download` на видимом материале независимо от статуса; отдача — только `scan_state='ready'` (FR-058).
- Скачивание файла и выгрузка .md фиксируются в аудите (FR-140, 16.1-108).

### 6.5. Счётчик ссылок и сборка мусора

- **Быстрый путь**: инкремент/декремент `ref_count` при привязке/отвязке (удаление материала — soft-delete, ссылки версий сохраняются; счётчик не меняется).
- **Истина — периодическая сверка** `cas_reconcile`: фактический `ref_count` = COUNT(ссылок из `materials.current_file_id` ∪ `material_versions.snapshot.file_id`); ссылки soft-deleted материалов **учитываются** — файлы удалённых материалов не собираются (просмотр удалённого — СА, FR-090; физическое удаление контента удалённого материала не предусмотрено, версии бессрочны — FR-147). Расхождения исправляются; объекты silo с нулевым фактическим счётчиком — кандидаты на удаление.
- **Сборка мусора** `cas_gc` (HLD §12 №6): удаляет из silo объекты `ab/cd/*`, отсутствующие в `file_objects` (осиротевшие PUT при сбоях) и объекты с нулевым счётчиком после периода отсрочки (`cas_gc_delay_hours` — 24 ч `[уточнение LLD]`, §2.5; защита от гонок со вставкой); `pdf/*` — при отсутствии соответствующего исходника. Удаление материалов — soft-delete, физическое удаление объектов — только этой задачей (4.1, FR-147: версии бессрочны → реальные удаления редки).

## 7. Поиск (9, FR-110–127; HLD §12 №5)

### 7.1. FTS-вектор

- `materials.search_lang text` (конфигурация FTS: значение из `fts_languages`; атрибут «Язык» не задан → `russian`, FR-122; язык вне конфигурации → `simple` — без стемминга, 9.7).
- `materials.search_tsv tsvector` — не generated (зависит от динамической конфигурации); пересчёт сервисом при записи:
  - вес A — название;
  - вес B — значения атрибутов (строковое представление, включая «осиротевшие», 16.1-115), названия тегов;
  - вес C — текстовое представление.
  
  `setweight(to_tsvector(cfg, name),'A') || setweight(to_tsvector(cfg, attrs+tags),'B') || setweight(to_tsvector(cfg, text),'C')`.
- **Пересчёт при изменении**: названия, текста, значений атрибутов, тегов, типа (смена состава атрибутов), значения «Язык», конфигураций FTS (US-048), атрибута/словаря (переименование значений меняет выдачу) — триггерная логика на сервисных мутациях + периодическая полная пересборка — задача `maintenance.fts_rebuild` (§9, защита от расхождений).
- Метаданные-даты в вектор не входят (фильтруются, не ищутся полнотекстом, 9.2).

### 7.2. Индексы

GIN `search_tsv`; GIN trgm `name`, `text_content` (частичное совпадение — при включённом переключателе, FR-113/114). Для выдачи с фильтрами — композитные индексы §2.4. Эксплуатационная настройка этапа 11 (Приложение А №38): `fastupdate = off` на трёх GIN-индексах поиска (миграция 0010_search_gin_tuning) — под потоком вставок pending list рос до ~800 страниц и давал пиковые хвосты p95; поток вставок MVP мал, прямой апдейт индекса не критичен.

### 7.3. Разбор запроса и выполнение

- Запрос пользователя → `websearch_to_tsquery(search_lang, q)`: слова — И; фраза в кавычках — фраза (FR-113). Функция не бросает синтаксических ошибок (невалидный синтаксис интерпретируется литерально), поэтому отдельный фолбэк не нужен; экранирование/литеральная интерпретация — ожидаемое поведение (безопасность SQL-инъекций обеспечивается параметризацией).
- Механика исполнения (Приложение А №37): tsquery в предикате/ранжировании/подсветке строится с **константным** конфигом — запрос раскладывается по distinct `search_lang` (`websearch_to_tsquery('russian'::regconfig, q) OR websearch_to_tsquery('english'::regconfig, q)`, каждая ветка со своим `search_lang = <cfg>`); форма «от колонки» (`cast(search_lang AS regconfig)`) в условие GIN-индекса не извлекается → merge join/seq scan всей таблицы (под нагрузкой p95 поиска до 11 с). Ранжирование — `case()` по `search_lang` (семантика «конфигурация материала» FR-122 сохранена).
- Переключатель частичного совпадения (FR-113): включён → дополнительно `name ILIKE '%:q%' OR text_content ILIKE '%:q%'` (основной механизм подстроки, FR-114; ускоряется тем же GIN trgm-индексом, §7.2 [уточнение LLD] — Приложение А №30) и `name % :q` (pg_trgm similarity по названию — индексируемый оператор, Приложение А №36: `similarity(text_content, q)` для длинных текстов математически недостижима — trgm-сходство всей строки с коротким запросом всегда ниже порога); порог оператора — параметр реестра trgm_similarity_threshold (§2.5), устанавливается `SET LOCAL pg_trgm.similarity_threshold` в транзакции запроса; для запросов короче `short_query_min_len` (3, §2.5) — только ILIKE (trgm-similarity на очень коротких строках неинформативен).
- Фильтры (FR-115, FR-116): тип, группа (включая подгруппы: `g.path LIKE '<group.path>%'`), статус, автор, диапазон дат публикации, атрибуты (операторы по типу значения: строка — точное/подстрока; число/дата — диапазон; url — точное; справочник — значение; многозначные — any-of), теги (any-of), «Включая архив».
- Видимость: предикат §3.2 inline в запросе (FR-112); «Архив» скрыт по умолчанию (FR-088).
- Фильтр «только мастера/только подчинённые» (FR-120): `master_id IS NULL` / `IS NOT NULL`.

### 7.4. Ранжирование и подсветка

- Релевантность: `ts_rank(search_tsv, query)` с весами setweight + `similarity(name, :q)` (частичные) — взвешенная сумма (`0.7 * ts_rank + 0.3 * similarity` `[уточнение LLD]`, коэффициенты — параметры реализации, §14-1); сортировки: релевантность, название, дата изменения (по умолчанию в списках — FR-117), дата публикации.
- Подсветка: `ts_headline(search_lang, text, query, 'StartSel=<mark>,StopSel=</mark>,MaxFragments=2,MaxWords=35,MinWords=15')` — фрагмент текста в выдаче; в названии — выделение совпадения на клиенте (FR-118).
- Пагинация: page/per_page (50, FR-121) + total (COUNT по предикату — по подзапросу **без** ORDER BY, иначе PG вычисляет ранжирование всех совпавших строк ради подсчёта, Приложение А №38; кэшируется на страницу).

### 7.5. Поиск групп

Отдельный блок выдачи (FR-119, US-036): `SELECT * FROM groups WHERE is_deleted = false AND (name % :q OR name ILIKE '%:q%')` + право `view` по предикату групп; порядок — по similarity. Механизм — trgm (не FTS-вектор: группы без текста; 9.2, HLD §6.6).

### 7.6. Аналитика поиска (9.9, FR-127)

- `search_events`: `id`, `query_normalized` (lower, trim), `result_count`, `created_at`; без ПДн (user_id не хранится).
- `search_opens`: `search_event_id`, `material_id`, `created_at` — факт открытия из выдачи (CTR, 3.2); фронтенд отправляет событие открытия при переходе из результатов — `POST /search-opens` (§12.3, fire-and-forget; ошибки приёма не влияют на переход).
- Свёртка `analytics_rollup` (worker, ежедневно) в `search_analytics` за период: `{period_start, query, hit_count, zero_result_count, open_count}`; доля материалов с текстом — мгновенный агрегат (COUNT по `text_content IS NOT NULL` среди неудалённых). Raw-события — хранение `analytics_raw_retention_days`, затем пакетное удаление. Персональных данных нет (FR-127).

## 8. Уведомления (11, FR-134–139)

### 8.1. События и получатели

- События `notification_events` публикуются **в транзакции** изменения материала (§4.1): переходы статусов (маппинг на event_type: `→ in_review` — `material_sent_to_review`; возвраты из `in_review` в `draft` — `material_rejected` (16.1-113: отзыв утверждения `approved→draft` события не создаёт); `→ archived` — `material_archived` (одиночная) и `child_auto_archived` (каскад — по событию на каждый подчинённый); правка контента в `in_review` — `material_changed_on_review`; изменение мастера по критерию `master_change_criterion` — `master_changed` (16.1-111: смена мастера подчинённого/отвязка события не создают)). Общий триггер `status_changed` — все переходы, если включён; специализированные имеют приоритет и исключают дубли (FR-134: диспетчер отбрасывает `status_changed` для переходов, уже покрытых специализированным событием).
- **Прямое уведомление** `file_blocked` (FR-058): создаётся конвейером файлов напрямую в `notifications` (вне триггеров), получатели — автор материала (`fact_author` по `materials.author_id` загружаемого файла) и все СА (носители шаблона «Системный администратор», по `user_roles`); инициатор — система (HLD §6.5).
- **Вычисление получателей** (диспетчер, FR-135): по `trigger_configs`: `role` — носители роли-шаблона (все пользователи с ролью; без привязки к объекту — настройки не знают объект заранее, получатели вычисляются на событии); `fact_author`/`fact_signatory`/`fact_last_editor` — документные факты материала; `permission_holder` — носители права на материале/группе (например, рецензенты — `review`, 7.6).
- **Исключения**: инициатор события (FR-138); деактивированные (FR-139, `is_deactivated`); сервисные УЗ (у получателя-сервисной УЗ email и in-app не доставляются — FR-013: признак УЗ `is_service` в users, заполняется сверкой по принадлежности к сервисным клиентам Keycloak).

### 8.2. Диспетчер, анти-шум, каналы

- Диспетчер — задача worker с интервалом ≤ 15 с (NFR-007: in-app ≤ 30 с): выбирает `notification_events WHERE processed=false`, вычисляет получателей, применяет анти-шум — окно `anti_noise_window_minutes`: `dedup_key = <event_type>:<material_id>:<recipient_id>`; повторное событие в окне не создаёт новое уведомление (11.3); создаёт строки `notifications` (channel=in_app) и email-задачи.
- **Email**: активен при настроенном SMTP (FR-136); задачи очереди `notifications.email` с ретраями (§9); при ненастроенном — email-задачи не создаются, in-app работает (US-040 A1). Адрес — из `users.email_cache` (§2.2, заполняется при первом запросе и сверкой §10); при пустом кэше — фолбэк Admin API `GET /admin/realms/<realm>/users/<id>` с обновлением `email_cache`. Email в системе не дублируется (FR-151 — уникальность проверяет Keycloak при задании адреса; кэш — проекция адреса истины).
- **Дайджест** (FR-138): периодическая задача (интервал `digest_interval_minutes`): сводка непрочитанных получателя за период одним письмом; события, вошедшие в дайджест, помечаются `included_in_digest_at` (§2.2) — дедупликация каналов согласована (11.3); строки `notifications` в дайджесте не сбрасывают `read_at` (дайджест отражает те же непрочитанные).
- **Прочтение**: индивидуальное `read_at` (FR-137); очистка in-app — задача по возрасту ≥ срока аудита (FR-137).

## 9. Очереди и фоновые задачи (NFR-005–007, NFR-014; HLD §12 №7)

| Имя задачи Celery | Триггер | Ретраи | Идемпотентность |
|---|---|---|---|
| `files.scan` | загрузка нового FileObject | 5 попыток, экспоненциально (30 с → ×2) | повторный вызов по тому же FileObject безопасен |
| `files.convert` | `scan_state='ready'` + офисный mime | 3 попытки (10 мин таймаут, NFR-006) | результат — PUT `pdf/<hex>`, перезапись |
| `notifications.dispatch` | расписание каждые 15 с | не требуется (повторный прогон по `processed=false`) | дедуп_key исключает дубли |
| `notifications.email` | диспетчер | 5 попыток, экспоненциально | state в notifications |
| `notifications.digest` | расписание (параметр) | — | окно дайджеста по времени |
| `maintenance.audit_cleanup` | ежедневно | — | пакетное удаление по возрасту (FR-141) |
| `maintenance.inapp_cleanup` | ежедневно | — | по возрасту ≥ аудита (FR-137) |
| `maintenance.analytics_rollup` | ежедневно | — | пересвёртка периода безопасна |
| `maintenance.cas_gc` / `cas_reconcile` | еженедельно / ежедневно | — | §6.5 |
| `keycloak.sync` | расписание (5 мин) | 3 попытки | полная выгрузка — результат заменяет |
| `maintenance.integrity_check` | еженедельно | — | сверка инвариантов §2.3 (счётчики ссылок, даты/статусы, осиротевшие ссылки) |
| `maintenance.fts_rebuild` | еженедельно | — | полная пересборка `search_tsv` (§7.1); пересчёт идемпотентен |

- Источник истины по состояниям — `system_tasks` (NFR-014); брокер Valkey — транспорт (HLD §3.2); восстановление после сбоя — задачи в `queued` перезапускаются диспетчером при старте worker (reconcile очереди из БД).
- Метрики для Prometheus: глубина и возраст очередей (из `system_tasks`), доля ошибок (NFR-019) — экспозер в api `/metrics` и отдельный экспозер worker.
- **Реализация метрик (этап 11, NFR-019):** worker-экспозер `:9808` — `kb_queue_depth{task_type,state}` (число задач по типу/состоянию), `kb_queue_age_seconds{task_type}` (возраст старейшей queued-задачи), `kb_queue_error_ratio{task_type}` (доля failed среди завершённых за окно 24 ч); api-экспозер `/metrics` — middleware: `kb_api_requests_total{method,path,status}` (path — нормализованный маршрут: uuid/числовые сегменты → `{id}`; исключены /metrics, /healthz, /readyz), `kb_api_request_latency_seconds{method,path}` (histogram, buckets 0.05–10 с), `kb_api_requests_in_progress{method}`. Состав правил алертинга (15 правил, 5 групп) и HTTP/TCP-пробы сервисов без экспозера (blackbox-exporter: keycloak/converter/silo/nginx/valkey) — в compose-развертывании (`deploy/prometheus/alerts.yml`); канал алертинга — email СА (alertmanager; при ненастроенном SMTP — заглушка, US-040 A1).
- **Бэкап-контур (этап 11, NFR-012, HLD §8.2):** единый tools-образ (postgres:18.6 + pgBackRest из PGDG + restic). WAL-архив — `archive_command` postgres-контейнера (`pgbackrest archive-push`, том `backups`, `archive_timeout=60s` → RPO ≤ 1 ч); базовые копии — цикл `pgbackrest.sh` в postgres-контейнере (pgBackRest требует локальное соединение с кластером и pg1-path; полная по воскресеньям, инкременты пн–сб; stanza `kb` = весь кластер — БД kb + keycloak). Файлы silo — restic-снапшоты тома silodata сразу после успешной pgBackRest-копии (согласование по времени — единая точка восстановления; CAS-объекты неизменяемы). Координация — маркеры в томе `backups` (`status/pgbackrest.done|failed`); свежесть копий — textfile `prometheus/backup_state.prom` (`kb_backup_freshness_seconds`, `kb_backup_failed`) через node-exporter → алерты BackupStale (25 ч) / BackupFailed. Процедуры восстановления — инструкция `deploy/README.md` (§4, NFR-013).

## 10. Интеграция Keycloak (5.3, 13.2, FR-001–011, 16.1-118)

- **Introspection на каждый запрос** (FR-011, без кэша — HLD §6.1): `POST /realms/<realm>/protocol/openid-connect/token/introspect` (Basic-auth клиентские учётные данные api-клиента); таймаут 2 с, 1 повтор; любой сбой/`active=false` → `401` (fail-closed). Из introspection извлекаются: `sub` (keycloak_id), `preferred_username`/`name` (display_name), `email` (на лету; обновление `users.email_cache` при отличии — 16.1-119), признак сервисного клиента (client credentials — токен без session).
- **Периодическая сверка** (worker, `keycloak.sync`): Admin API `GET /admin/realms/<realm>/users?briefRepresentation=true` страницами по 100 (параметр `KEYCLOAK_SYNC_PAGE`). `[уточнение LLD]` к HLD §6.1 («инкрементально по времени изменения»): Admin API Keycloak 26 не предоставляет выборку по времени изменения; при объёме УЗ (до 600) полная выгрузка страницами проще и надёжнее — инкрементальность не требуется. Сверка: список `id` + `enabled` + `email` → обновление `users.is_deactivated` (обе стороны: `enabled=false` → деактивация; `enabled=true` при `is_deactivated=true` → реактивация — деактивация обратима активацией в Keycloak/сверкой) и `users.email_cache` (16.1-119); новые пользователи — при первом входе (§6.1 HLD), не сверкой. Токен сверки — client credentials клиента `kb-api`; для Admin API Keycloak ≥26.8 требуется встроенный client scope `kc-admin-api` (default client scope клиента) и роль `realm-management/view-users` сервисному аккаунту (deploy-требование: `deploy/keycloak/realm-kb-test.json` — `defaultClientScopes` + `service-account-kb-api`; на существующем стеке — kcadm).
- **Служебные последствия деактивации** (FR-011, FR-012): при переходе `is_deactivated false → true`: исключение из рассылок (учитывается диспетчером); подсчёт неархивированных материалов автора (для показа СА); если пользователь — единственный носитель `review` в какой-либо группе (носители `permission_holder(review)` на группе) → создание `service_tasks(transfer_review_right)`; закрытие задачи — только после назначения права другому пользователю (US-004).
- **Карта ролей**: роли-шаблоны системы ↔ Keycloak не связаны (роли назначаются в системе, FR-007); сервисные УЗ — client credentials, их User-запись создаётся при первом запросе с флагом `is_service` (FR-013: авторство закрепляется за УЗ, уведомления не доставляются).
- Сессия 8 ч — SSO Session Idle Keycloak; TTL access-токена 15 мин (консоль Keycloak; защита в глубину — HLD §6.1).

## 11. Аудит (12.1, FR-140–143)

- `audit_entries`: `id bigserial PK`, `occurred_at timestamptz`, `actor_user_id uuid NULL` (NULL — системные события: конвейер файлов), `actor_is_service boolean`, `action text`, `object_type text`, `object_id uuid NULL`, `details jsonb`. Append-only: без UPDATE/DELETE в коде; очистка — только пакетная по возрасту (`audit_retention_days`), задача `audit_cleanup` (FR-141).
- **Коды действий** (`action`): `material.create/update/status_change/delete/file_upload/file_download/text_export`, `comment.create`, `material.move/copy/master_change`, `group.create/rename/delete`, `type.create/rename/delete`, `attribute.create/update/delete`, `dictionary.create/rename/value_add/value_delete`, `tag.create/delete/merge`, `transition_matrix.change`, `role.create/update/clone/delete`, `user.role_assign/role_revoke/deactivate`, `snapshot.create/update/delete`, `settings.change`, `audit.export` — полнота по FR-140 (включая скачивание файлов, выгрузку .md, административные операции; просмотры — нет, FR-142).
- **Выгрузка JSON** (FR-143): `GET /api/v1/audit/export` — потоковая генерация (курсор, NDJSON); сама выгрузка фиксируется записью `audit.export`.
- Просмотры не фиксируются (FR-142); агрегаты — только через search_events (§7.6).

## 12. API (10, FR-128–133, NFR-021)

### 12.1. Соглашения

- Базовый путь `/api/v1` (FR-130); OpenAPI 3.1 поставляется с системой (`GET /api/v1/openapi.json`, NFR-021, US-053 шаг 4).
- Аутентификация: `Authorization: Bearer <token>` + introspection (§10, FR-129).
- Права: предикат §3.2 на каждом запросе; `401` — нет/невалидный токен; `403` — нет права или объект невидим (в т.ч. прямая ссылка на невидимый материал — FR-067, US-014 A1).
- Пагинация (FR-131): `?page=1&per_page=50` (макс. 200); ответ-конверт `{"items": [...], "total": 1234, "page": 1, "per_page": 50}`.
- Сортировка (FR-117, FR-131): `?sort=<field>&order=asc|desc`; допустимые поля — по ресурсу.
- ETag/If-Match на материалах (FR-095): `ETag: "<version>"`; мутации без If-Match → `428 Precondition Required`.
- Ошибки: RFC 7807 `application/problem+json`: `{type, title, status, detail, code, params}`; стабильные `code` — таблица ниже (HLD §12 №2).
- Идемпотентность: загрузка файла — не идемпотентна (новая версия); дедупликация CAS — §6.2 (HLD §7.1).
- Даты — ISO 8601 UTC (NFR-018); текст — UTF-8; интерфейсные сообщения ошибок — русские (NFR-018).

### 12.2. Доменные коды ошибок

| Код | HTTP | Условие |
|---|---|---|
| `ACCESS_DENIED` | 403 | нет права/объект невидим (FR-067) |
| `VERSION_CONFLICT` | 412 | If-Match не совпал (FR-093/095) |
| `NAME_CONFLICT` | 409 | неуникальное название в группе (FR-017/027); перемещение — без автопереименования (16.1-66) |
| `FILE_REQUIRED` | 409 | переход без файла (FR-028/076) |
| `FILE_NOT_READY` | 409 | переход: файл не прошёл проверку (FR-058, US-015 A1) |
| `FILE_BLOCKED` | 409 | файл заражён (загрузка — §6.2; конвейер — уведомление FR-058) |
| `FILE_TOO_LARGE` | 413 | превышен лимит (FR-031) |
| `MIME_NOT_ALLOWED` | 415 | mime вне базового набора и `mime_extra` (FR-056) |
| `TRANSITION_NOT_ALLOWED` | 409 | нет правила матрицы/защищённый статус (FR-072/073) |
| `CASCADE_CONFIRM_REQUIRED` | 409 | каскадная архивация без подтверждения; `params.children_count` (FR-039) |
| `MASTER_NOT_PUBLISHED` | 409 | публикация подчинённого раньше мастера (FR-042) |
| `MASTER_STATUS_LOCKED` | 409 | мастер с подчинёнными в «Публикации» (FR-041) |
| `MASTER_DELETE_FORBIDDEN` | 409 | удаление мастера с подчинёнными (FR-040) |
| `GROUP_DELETE_FORBIDDEN` | 409 | ветка с мастером и подчинёнными вне ветки (FR-020) |
| `ATTRIBUTE_REQUIRED_MISSING` | 409 | незаполнены обязательные атрибуты; `params.missing[]` (FR-048/049) |
| `ENTITY_IN_USE` | 409 | удаление используемого атрибута/типа/тега/значения справочника (FR-050/054/047) |
| `TAGS_LIMIT_EXCEEDED` | 409 | > 20 тегов (FR-052) |
| `ATTRIBUTES_LIMIT_EXCEEDED` | 409 | > 50 атрибутов на тип (FR-044) |
| `NAME_TOO_LONG` | 400 | > 255 символов (FR-017/027) |
| `ARCHIVED_SOURCE_RULE_FORBIDDEN` | 400 | правило матрицы с `from_status='archived'` (FR-073, §2.6) |
| `RESOURCE_NOT_FOUND` | 404 | объект не найден или невидим |
| `FILE_PENDING_SCAN` | 409 | файл ещё проверяется; повторите позже (§6.2) |
| `NOT_IMPLEMENTED` | 400 | зарезервированное значение параметра вне MVP (`search_type`, §12.3) |
| `PRECONDITION_REQUIRED` | 428 | мутация материала без If-Match (FR-095, §12.1) |
| `VALIDATION_ERROR` | 400 | ошибки схемы запроса; `params.errors[]` |

### 12.3. Состав эндпоинтов (верхний уровень)

| Метод и путь | Назначение | Права/условие | Требования |
|---|---|---|---|
| `GET /me` | профиль из токена | аутентификация | FR-151 |
| `GET /users`, `GET /users/{id}` | список/карточка: роль, счётчик неархивированных материалов автора (при деактивации — US-004 шаг 3) | СА | FR-005, FR-006 |
| `DELETE /users/{id}` | деактивация (soft) | СА | FR-006 |
| `GET/POST /roles`, `PATCH/DELETE /roles/{id}`, `POST /roles/{id}/clone` | шаблоны ролей | СА | FR-008, FR-105 |
| `PUT/DELETE /users/{id}/roles/{role_id}` | назначение ролей | СА | FR-007 |
| `GET /groups`, `GET /groups/{id}`, `POST /groups`, `PATCH /groups/{id}` | дерево, CRUD | CRUD — СА; чтение — предикат групп (FR-103) | FR-015–017 |
| `DELETE /groups/{id}?confirm_rights=…` | удаление (физ./soft — решает система; предупреждение о правах) | СА | FR-018–020 |
| `GET /groups/deleted`, `GET /materials/deleted` | служебный раздел | СА | FR-021, FR-090 |
| `GET /types`, `POST /types`, `PATCH /types/{id}`, `DELETE /types/{id}` | CRUD типов | СА; удаление — при отсутствии неудалённых материалов (FR-050) | FR-043, FR-050 |
| `POST/DELETE /types/{id}/attributes/{attr_id}` | привязка/исключение атрибута | СА | FR-044, FR-051 |
| `GET/POST /attributes`, `PATCH/DELETE /attributes/{id}` | CRUD атрибутов | СА; удаление — при отсутствии использований (FR-054) | FR-044, FR-045 |
| `GET/POST /dictionaries`, `PATCH /dictionaries/{id}`; `POST/DELETE /dictionaries/{id}/values` | CRUD справочников и значений | СА; удаление значения — запрет при использовании (FR-047) | FR-046–049 |
| `GET/POST /tags`, `POST /tags/{id}:merge` `{target_id}`, `DELETE /tags/{id}` | CRUD тегов, слияние (FR-053) | СА; удаление — при отсутствии использований (FR-054) | FR-052–054 |
| `POST /search-opens` | приём события открытия из выдачи | аутентификация | FR-127, §7.6 |
| `GET /materials` | список с фильтрами/сортировкой/пагинацией | предикат | FR-112, FR-115–117 |
| `POST /materials` | создание (в т.ч. пустышка) | `create` в группе | FR-024–026 |
| `GET/PATCH/DELETE /materials/{id}` | карточка, правка (If-Match), soft-delete | предикат + `edit`/`delete` | FR-026, FR-084, FR-090 |
| `POST /materials/{id}/file` (multipart) | загрузка/замена файла | `edit` | FR-029–031, §6.2 |
| `GET /materials/{id}/file` | скачивание исходника (Range) | `download`; `scan_state=ready` | FR-058, FR-062, FR-067 |
| `GET /materials/{id}/file-state` | состояние конвейера (`scan_state`, `pdf_state`) для опроса из карточки | предикат | FR-058–061 |
| `GET /materials/{id}/pdf` | PDF-предпросмотр | `view`/участие; `ready_pdf` | FR-059, FR-061 |
| `GET /materials/{id}/text.md` | скачивание текста | `download` | FR-107 |
| `POST /materials/{id}/transitions` `{to_status, confirm_cascade}` | переход по матрице | права перехода | §4, FR-070–076 |
| `GET /materials/{id}/transitions` | доступные переходы | предикат | FR-070 |
| `GET /materials/{id}/status-log` | журнал статусов | видимость материала | FR-075, FR-145 |
| `POST /materials/{id}/master` / `DELETE /materials/{id}/master` | смена мастера/отвязка | `edit`; видимость нового мастера | FR-036, FR-108 |
| `POST /materials/{id}/move` `{group_id}` | перемещение | `move` в обеих группах + `edit` | FR-037, FR-108 |
| `POST /materials/{id}/copy` `{group_id}` | копирование | `copy` + `create` в целевой | FR-092, FR-108 |
| `POST /materials/{id}/children` `{kind, language?…}` | создание подчинённого (адаптация/перевод) | `create` в целевой группе; мастер виден, статус по FR-033 | FR-033–035 |
| `GET /materials/{id}/versions`, `GET …/versions/{n}`, `GET …/versions/{n}/diff` | версии и diff | видимость материала | FR-145, FR-146 |
| `POST /materials/{id}/versions/{n}/restore` | восстановление | `edit` + правила §4.2 | FR-148 |
| `GET/POST /materials/{id}/comments` | комментарии | чтение — видимость; создание — участники процесса | FR-096–098 |
| `GET/PATCH/DELETE /materials/{id}/permissions`, `POST /materials/{id}/permissions:copy-from-role` | снапшоты прав | СА | FR-100, FR-105 |
| (аналогично для групп) | права групп | СА | FR-100, FR-105 |
| `GET /search?q=…&search_type=fulltext\|vector\|hybrid` | поиск; MVP — fulltext, прочие значения зарезервированы (400 `NOT_IMPLEMENTED`) | предикат в запросе | FR-133, §7 |
| `GET /notifications`, `POST /notifications/{id}:read`, `POST /notifications:read-all` | лента, прочтение | получатель | FR-137 |
| `GET/PUT /notification-triggers` | конфигурация триггеров | СА | FR-134/135 |
| `GET/POST /transition-rules`, `DELETE /transition-rules/{id}` | CRUD матрицы переходов (is_protected — только чтение); создание правила с `from_status='archived'` → 400 `ARCHIVED_SOURCE_RULE_FORBIDDEN` | СА | FR-070–074 |
| `GET /audit`, `GET /audit/export` | журнал, выгрузка NDJSON | СА; экспорт фиксируется | FR-140–143 |
| `GET /analytics/search` | аналитика поиска | СА | FR-127 |
| `GET/PUT /settings` | реестр параметров | СА | NFR-020, US-048 |
| `GET /service-tasks`, `POST /service-tasks/{id}:close` | задачи СА | СА | FR-012 |
| `GET /tasks` | состояния задач антивируса/конвертации/email | СА | NFR-014 |
| `GET /metrics` | Prometheus | внутренняя сеть | NFR-019 |

### 12.4. Пример контракта (фрагмент OpenAPI)

```yaml
paths:
  /api/v1/materials/{id}:
    get:
      summary: Карточка материала
      parameters: [{name: id, in: path, required: true, schema: {type: string, format: uuid}}]
      responses:
        "200": {description: OK, content: {application/json: {schema: {$ref: '#/components/schemas/Material'}}}}
        "403": {$ref: '#/components/responses/Problem'}
    patch:
      summary: Правка материала (If-Match обязателен)
      parameters: [{name: If-Match, in: header, required: true, schema: {type: string}}]
      requestBody: {content: {application/json: {schema: {$ref: '#/components/schemas/MaterialPatch'}}}}
      responses:
        "200": {description: OK}
        "409": {$ref: '#/components/responses/Problem'}   # NAME_CONFLICT, ATTRIBUTE_REQUIRED_MISSING…
        "412": {$ref: '#/components/responses/Problem'}   # VERSION_CONFLICT
        "428": {$ref: '#/components/responses/Problem'}   # PRECONDITION_REQUIRED (без If-Match)
components:
  responses:
    Problem:
      description: Ошибка
      content:
        application/problem+json:
          schema:
            type: object
            properties:
              type: {type: string}
              title: {type: string}
              status: {type: integer}
              detail: {type: string}
              code: {type: string}
              params: {type: object}
```

## 13. Трассировка LLD → требования

| Область | Требования | Раздел LLD |
|---|---|---|
| Учётные записи, роли | FR-001–014 | §2.2, §10, §12.3 |
| Группы | FR-015–023 | §2.2, §2.3, §12.3 |
| Материалы и метаданные | FR-024–031 | §2.2, §6.2 |
| Мастер — подчинённый | FR-032–042 | §2.3, §4, §12.3 |
| Типы, атрибуты, теги | FR-043–054 | §2.2, §2.3, §12.3 |
| Файлы, антивирус, предпросмотр | FR-055–064, NFR-005/006, NFR-010 | §6, §12.3 (file-state) |
| Жизненный цикл | FR-065–095 | §4, §5, §12.3 (transition-rules) |
| Комментарии | FR-096–098 | §2.2, §12.3 |
| Права | FR-099–109 | §3 |
| Поиск и аналитика | FR-110–127, NFR-001 | §7, §12.3 (search-opens) |
| API | FR-128–133, NFR-021 | §12 |
| Уведомления | FR-134–139, NFR-007 | §8 |
| Аудит и версии | FR-140–148 | §5, §11 |
| Безопасность | FR-149–152 | §2.2 (email_cache, 16.1-119), §10, §11, §12.1 |
| Надёжность, эксплуатация | NFR-008–014, NFR-019/020 | §2.5, §9, §10 |
| Открытые вопросы HLD | HLD §12 №1–8 | №1 §2; №2 §12; №3 §3; №4 §5; №5 §7; №6 §6; №7 §9, §8.2; №8 §10 |

## 14. Открытые вопросы для шага [5]

| № | Вопрос | Куда |
|---|---|---|
| 1 | Точные пороговые значения кэшей (TTL, объёмы), пулов соединений и коэффициентов ранжирования (0.7/0.3, §7.4) — по результатам нагрузочного тестирования | реализация |
| 2 | Состав стартовых значений справочника «Язык» и связывание атрибута с типами — регламент внедрения (шаг [6]; FR-046, §2.6) | внедрение |
| 3 | Ретраи/таймауты Gotenberg и SMTP — уточнить при интеграционных испытаниях | реализация |

## Приложение А. Принятые замечания ревью LLD

Перечень замечаний по раундам ревью; источники согласования — CONCEPT.md 16.1, REQUIREMENTS.md, HLD.md. Замечания заказчика помечаются в заголовке раунда. Заполняется по итогам раундов ревью.

### Раунд 3 (реализация MVP, ред. 0.2 → 0.3, 09.11.2026)

Замечания, выявленные при реализации этапов 7–8 (мастер-подчинённый, поиск) и приёмки US-024–028, US-038, US-034–036, US-051 на живом стеке. Все приняты, внесены в ред. 0.3.

| № | Замечание | Решение |
|---|---|---|
| 30 | §7.3: trgm-оператор `%` (similarity) сопоставляет строку целиком и не находит подстроку в длинном названии («парац» не находит «Инструкция … Парацетамол») — FR-114 требует подстроку | Частичное совпадение при partial: ILIKE '%q%' (основной механизм, ускоряется тем же GIN trgm-индексом §7.2) + `similarity` дополнительно (сходство всей строки); ILIKE-фолбэк коротких запросов сохранён [уточнение LLD к §7.3] |
| 31 | §7.3/§7.4: `websearch_to_tsquery(search_lang, …)` не вызывается — PG требует regconfig первым аргументом; колонка varchar не приводится неявно | В реализации запросов/ранжирования/подсветки — явный каст `search_lang::regconfig` (механика исполнения, контракт §7 без изменений) |
| 32 | §7.1: пересчёт search_tsv при изменении справочников/атрибутов («переименование значений меняет выдачу») не имел точки вставки в сервисных мутациях | Реализация: update_search_vector вызывается при create/update/restore материала, загрузке файла, привязке атрибута к типу, слиянии тегов; изменение значений справочника покрывается fts_rebuild (полная пересборка, §9) |

### Раунд 5 (реализация MVP, ред. 0.4 → 0.5, 09.11.2026)

Замечания реализации этапа 11 (НФТ и приёмка): мониторинг (NFR-019), бэкап-контур (NFR-012), интроспекция (§10), поисковые оптимизации по итогам нагрузочного тестирования (NFR-001, §7). Все приняты, внесены в ред. 0.5.

| № | Замечание | Решение |
|---|---|---|
| 33 | §9: состав метрик очередей (окно доли ошибок, нормализация маршрутов API, перечень правил алертинга и проб) не конкретизирован — реализация этапа 11 требует контракта | Дополнен §9 (реализация метрик: имена/лейблы/окно 24 ч; алерты — deploy/prometheus/alerts.yml); механика реализации, контракт §12 без изменений |
| 34 | §9/HLD §8.2: бэкап-контур не был детализирован до уровня механики (кто исполняет pgbackrest, координация БД/silo-копий, экспозиция свежести) | Дополнен §9 (бэкап-контур: tools-образ, archive_command, маркеры, textfile-состояние); процедуры восстановления — deploy/README.md (NFR-013, шаг внедрения [6]) |
| 35 | §10: код интроспекции проверял только HTTP-статус; Keycloak на истёкший/отозванный токен отвечает 200 `{"active": false}` (без sub) — запрос падал KeyError 'sub' → 500 вместо оговорённого fail-closed 401 | Реализация приведена к §10: active=false/отсутствие sub → 401 UNAUTHENTICATED (юнит-тесты test_introspect.py); контракт §10 без изменений |
| 36 | §7.3: `similarity(text_content, q) > порога` в фильтре partial математически недостижим для длинных текстов (trgm-сходство всей строки с коротким запросом < порога 0.3 всегда), а её неиндексируемая форма давала seq scan всей таблицы (p95 partial 11 с под нагрузкой) | Фильтр partial: ILIKE `'%q%'` (основной механизм, №30) + индексируемый оператор `name % q` (pg_trgm по GIN trgm-индексу §7.2); порог оператора — тот же параметр реестра trgm_similarity_threshold (§2.5), устанавливается `SET LOCAL pg_trgm.similarity_threshold` в транзакции запроса [уточнение LLD к §7.3] |
| 37 | §7.3/§7.4: форма «от колонки» `websearch_to_tsquery(search_lang::regconfig, q)` в предикате и ранжировании не извлекается в условие GIN-индекса (tsquery зависит от строки) → merge join/seq scan всех материалов; подсветка ts_headline выполнялась отдельным запросом на каждый материал страницы (N+1, 20 round-trips) | Предикат и ts_rank раскладываются по distinct search_lang с константным конфигом (`literal(cfg)`) → GIN BitmapOr; релевантность — через `case()` по search_lang (семантика «конфигурация материала» FR-122 сохранена); подсветка — один батч-запрос по id страницы (механика исполнения, контракт §7.1–7.5 без изменений) |
| 38 | §7.2/эксплуатация: под нагрузкой (поток вставок) GIN pending list (fastupdate=on) рос до ~800 страниц — поиски линейно сканируют его, достижение лимита чистится вставляющим соединением синхронно → пиковые хвосты p95; COUNT total по подзапросу с ORDER BY relevance вычислял ранжирование всех совпавших строк ради подсчёта; generic-планы подготовленных запросов (psycopg3 prepare после 5 исполнений) не оценивают селективность параметризованных tsquery/trgm → бимодальность 50↔1850 мс | Миграция 0010_search_gin_tuning: `fastupdate=off` на трёх GIN-индексах поиска (поток вставок MVP мал — прямой апдейт индекса не критичен); COUNT total — по подзапросу без ORDER BY; `plan_cache_mode=force_custom_plan` — параметр окружения compose (postgres). Для достоверности НТ (NFR-008/009): нагрузочный корпус требует лексического разнообразия — словарь из ~20 слов даёт совпадение ~90% корпуса на запрос-термин и обесценивает замер |

### Раунд 2 (внутреннее, ред. 0.2, 08.11.2026)

Контрольное ревью внесённых правок раунда 1 и смежных мест; замечания №23–29 приняты, все внесены в ту же ред. 0.2.

| № | Замечание | Решение |
|---|---|---|
| 23 | §2.6 ссылался на «CRUD матрицы (§12.3)», но эндпоинтов матрицы в §12.3 не было | Добавлена строка `/transition-rules` (GET/POST/DELETE; is_protected — только чтение); UNIQUE (from_status, to_status) и частичный индекс — §2.2/§2.4 |
| 24 | Запрет правил с `from_status='archived'` не имел кода ошибки | Введён `ARCHIVED_SOURCE_RULE_FORBIDDEN` (400, §12.2); сид §2.6 упрощён |
| 25 | Слияние тегов (FR-053, US-033 шаг 3) не имело механики в LLD | §2.2 (tags): UPDATE material_tags в транзакции; эндпоинт `POST /tags/{id}:merge` |
| 26 | Опрос состояния конвейера из карточки (US-011 шаг 2) не имел эндпоинта | Добавлен `GET /materials/{id}/file-state` (§12.3); §6.3 дополнен |
| 27 | Ссылка на «§8.3» (dedup_key) вела в несуществующий раздел — анти-шум в §8.2 | Исправлена на §8.2 |
| 28 | Ссылки на параметры в тексте («порог 0.3», «24 ч») не были привязаны к ключам реестра §2.5 | Уточнены: trgm_similarity_threshold/cas_gc_delay_hours/short_query_min_len (§7.3, §6.5) |
| 29 | email_cache упоминался в §2.2/§8.2, но потоки заполнения (introspection/сверка §10) не были сведены | §10 дополнен: обновление email_cache из introspection и сверки (16.1-119) |

### Раунд 1 (ред. 0.1 → 0.2, 08.11.2026)

Внутреннее ревью LLD (сверка с CONCEPT 2.17, REQUIREMENTS 1.6, SCENARIOS 0.8, HLD 1.1). Все 22 замечания приняты.

| № | Замечание | Решение |
|---|---|---|
| 1 | SQL-предикат §3.2: LIKE без `%` терял вышестоящие группы; потеряны скобки (A OR B AND C); `:is_super` отсутствовал в ветке published/archived; хвостовое `has_right` отрезало автора от черновика; `has_right` без определения | Переписан: `path LIKE g.path \|\| '%'`; скобки расставлены; `:is_super` в обеих ветках; хвост — `view` без права (видимость достаточна, FR-066), иные действия — по FR-102; `has_right` определён в преамбуле §3.2 |
| 2 | §2.3 требовал `scan_state='ready'` для привязки current_file_id — противоречит конвейеру §6.2 (привязка до проверки) | Ограничение перенесено на отдачу (§6.4) и переходы (валидатор 3); оговорка в §2.3 и §2.2 |
| 3 | §12.3: нет CRUD типов/атрибутов/справочников/тегов и приёма search_opens | Добавлены эндпоинты (HLD §7.2, §7.6) |
| 4 | Блок /users противоречил FR-006 (DELETE = деактивация) и HLD §6.1 (POST не нужен) | Пересобран: GET (роли, счётчик материалов), DELETE; POST явно не предусмотрен |
| 5 | §8.2 игнорировал users.email_cache | Приведено к email_cache + фолбэк Admin API; согласовано с FR-151 (16.1-119) |
| 6 | §6.2: судьба ref_count в гонке/при infected не определена; нет кода «повторите позже» | Гонка описана (инкремент только при фактической привязке); infected с ref_count=0 — под GC; введён FILE_PENDING_SCAN |
| 7 | cas_reconcile не оговаривал soft-deleted материалы | Ссылки soft-deleted учитываются — файлы не собираются (FR-090/147) |
| 8 | Сид значений «Язык» противоречил «состав — шаг [6]» (§14-2, FR-046) | Стартовые значения убраны из сида |
| 9 | Полная пересборка FTS без задачи | Добавлены task_type `fts_rebuild` и `maintenance.fts_rebuild` (§9) |
| 10 | Схема конвейера §6.3: convert шёл от infected | Convert отложен от `[ready]` + офисный mime |
| 11 | Параметры 0.3/24 ч/короткие запросы не в реестре §2.5 (NFR-020) | Добавлены trgm_similarity_threshold, cas_gc_delay_hours, short_query_min_len |
| 12 | Пользователь публикации (FR-086) без колонки | Источник — status_log.user_id последней записи to_status='published' |
| 13 | Нет кодов NOT_IMPLEMENTED, PRECONDITION_REQUIRED, «повторите позже» | Добавлены NOT_IMPLEMENTED (400), PRECONDITION_REQUIRED (428), FILE_PENDING_SCAN (409) |
| 14 | Коды аудита: нет move/copy/master_change, role.delete; «comment/create» | Добавлены material.move/copy/master_change, role.delete; comment.create |
| 15 | В notifications нет отметки «вошло в дайджест» | Добавлено included_in_digest_at |
| 16 | file_blocked: способ вычисления СА не определён | Автор по materials.author_id; СА — носители шаблона по user_roles |
| 17 | ETag оговорён неоднозначно | Явно: materials.version, не material_versions.number |
| 18 | Текстовые файлы сужены до text/markdown/plain против FR-029 (text/*) | Расширено до text/* (HTML исключён) |
| 19 | «Ключи — uuid» vs audit_entries bigserial | Исключение оговорено в §2.2 |
| 20 | UNIQUE material_versions (material_id, number) не в перечне индексов | Добавлен в §2.4 |
| 21 | websearch_to_tsquery не бросает ошибок — фолбэк недостижим | Переформулировано: литеральная интерпретация без фолбэка |
| 22 | Запрет правил матрицы с from_status='archived' не оговорён (FR-073) | Запрет добавлен: §2.6, эндпоинт /transition-rules, код ARCHIVED_SOURCE_RULE_FORBIDDEN (§12.2) |
