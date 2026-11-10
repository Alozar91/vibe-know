# RAG: получение релевантных данных — дизайн-предложение (черновик)

> Статус: реализуется (ветка `rag`). Не нормативный документ —
> при утверждении механика уйдёт в LLD (новые §2-таблицы, §9-задачи, §12-эндпоинты),
> поведенческие части — в CONCEPT §10.4/§9 (как пост-MVP шаг [7], CONCEPT §17).
>
> Ход реализации (§8): шаги 1–3 сделаны (схема+чанкеры+реестр+API конфигов —
> ea51760; конвейер+embedding-клиент+reconcile — 4f5ab63; retrieval+права —
> 67d874d); вопросы §9 решены. Остались: шаг 4 (UI), шаг 5 (MCP, опционально).

## 0. Требования (от заказчика, 10.11.2026)

1. Доступ к embedding-модели по OpenAI-совместимому API.
2. Поиск по материалам группы (возможно в вышестоящей группе, если не накладно).
3. Разные режимы чанкования, включая custom (определённые кодом), не только
   стандартные (символы / рекурсивный / markdown).
4. Вид чанкования задаётся на уровне группы; вопрос: можно ли группе и
   подгруппе задать разные виды — **да (см. §3.2)**.
5. Custom-чанкование расширяемо без пересборки системы (по возможности).
6. Получение данных учитывает права пользователя.

---

## 1. Сравнение вариантов хранения векторов

| Критерий | **A. pgvector в PostgreSQL** | B. Отдельное векторное хранилище (Qdrant) | C. Без векторного индекса (FTS + реранкер) |
|---|---|---|---|
| Фильтрация прав | **Ровно тот же SQL-предикат §3.2** (JOIN чанков → материалов) | Дублирование прав в payload (роли/владение/статусы) или пост-фильтрация — риск расхождения с §3.2 (deny, виртуальная роль, СА, авторство черновиков) | Предикат §3.2 напрямую (кандидаты уже из БД) |
| Масштаб (проект: 10k материалов, ~200–500k чанков) | Достаточно (HNSW; при фильтрах — iterative scan) | Избыточно | Падение качества полноты (recall) на переформулировках |
| Инфраструктура | +1 расширение, 0 новых сервисов | +1 сервис, sync двух хранилищ | 0 |
| Консистентность | Одна транзакция с контентом | eventual (очередь синкa) | — |
| Open Source / on-premise | да | да | да |

**Рекомендация: A (pgvector).** Решающий аргумент — требование 6: права
проверяются тем же предикатом `visible_materials_condition` (LLD §3.2), что и
везде; никакой второй реализации прав, которая неизбежно разъехалась бы с
эталоном (deny-правила, виртуальная роль «Все пользователи», видимость
черновиков по авторству/правам процесса, обход СА). Масштаб проекта
(≤ 10 000 материалов) pgvector закрывает с запасом. Вариант C — дешёвая
промежуточная ступень (режим «rerank»), реализуемая внутри A как частный случай;
Qdrant (B) — запасной путь при росте на порядки.

## 2. Схема данных (черновик LLD §2)

```sql
-- миграция 0011
CREATE EXTENSION IF NOT EXISTS vector;

-- Настройка чанкования по группам (наследуется, §3.2)
CREATE TABLE rag_group_configs (
  id uuid PRIMARY KEY, created_at timestamptz, updated_at timestamptz,
  group_id uuid UNIQUE NOT NULL REFERENCES groups(id),   -- явная настройка
  chunker text NOT NULL,          -- имя из реестра чанкеров (§4)
  params jsonb NOT NULL DEFAULT '{}'::jsonb,             -- параметры чанкера
  enabled boolean NOT NULL DEFAULT true                  -- false: не индексировать поддерево
);

-- Чанки текущей версии материала
CREATE TABLE rag_chunks (
  id uuid PRIMARY KEY, created_at timestamptz, updated_at timestamptz,
  material_id uuid NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  version_id uuid NOT NULL REFERENCES material_versions(id) ON DELETE CASCADE,
  group_id uuid NOT NULL REFERENCES groups(id),          -- денормализация для фильтра
  ord int NOT NULL,               -- порядок чанка в материале
  chunker text NOT NULL,          -- каким чанкером порезано
  content text NOT NULL,          -- текст чанка
  content_hash text NOT NULL,     -- sha256(content) — сверка актуальности
  meta jsonb NOT NULL DEFAULT '{}',  -- заголовки markdown, позиция, язык…
  embedding vector(:dim) NOT NULL,   -- :dim — из RAG_EMBEDDING_DIM (миграция)
  embedding_model text NOT NULL,
  UNIQUE (version_id, ord)
);
CREATE INDEX ix_rag_chunks_material ON rag_chunks(material_id);
CREATE INDEX ix_rag_chunks_group ON rag_chunks(group_id);
-- HNSW (m=16, ef_construction=64) + фильтруемый поиск — pgvector iterative scan
CREATE INDEX ix_rag_chunks_hnsw ON rag_chunks USING hnsw (embedding vector_cosine_ops);

-- Служебная очередь состояний — по образцу file_objects (§6.4 LLD):
-- состояние конвейера на материал: pending → chunked → embedded / error
ALTER TABLE materials ADD COLUMN rag_state text NOT NULL DEFAULT 'none';
ALTER TABLE materials ADD COLUMN rag_stale boolean NOT NULL DEFAULT false;
```

Примечания:
- Вектор фиксирует размерность при миграции (`RAG_EMBEDDING_DIM`, напр. 1536).
  Смена модели на иную размерность = новая миграция + полный переиндекс
  (редкая операция, оформляется как шаг обновления).
- Чанки принадлежат **версии** материала: новое версионирование = перечанкование;
  старые чанки версии удаляются при реиндексации (хранить историю векторов незачем).
- `rag_stale` ставится при изменении `text_content`/версии/конфигурации группы
  до завершения переиндексации — свёрка (beat-задача) находит отставших.

## 3. Конфигурация чанкования

### 3.1. Источники конфигурации

| Уровень | Что задаётся | Где хранится |
|---|---|---|
| Система | Чанкер по умолчанию, embedding-модель, порог гибридизации | `system_settings` (ключи `rag.*`, реестр 2.5 LLD) |
| Группа | Явный чанкер + параметры (или «наследовать») | `rag_group_configs` |
| Материал | Не настраивается (MVP) — наследует группу | — |

### 3.2. Ответ на вопрос 4: разные режимы для группы и подгруппы — да

Разрешение конфигурации для материала = **ближайшая группа по цепочке
предков, у которой есть явная строка в `rag_group_configs`**; не нашлась —
системный дефолт. Materialized path (`groups.path = /id1/…/idN/`) делает
поиск ближайшей настройки одним запросом:

```sql
SELECT gc.* FROM rag_group_configs gc
JOIN groups g ON g.id = ANY (parents_of(:group_path))
WHERE ... ORDER BY depth DESC LIMIT 1;
```

Следствия (правила, фиксируются явно):
- Подгруппа с собственной настройкой **не зависит** от смены настроек предков.
- Смена настройки группы **влияет только на поддеревья, которые наследуют**
  (без собственной строки) → переиндексировать именно их (path LIKE — дёшево).
- Переиндексация точечная: `rag.reindex_group_subtree(group_id)` — Celery-задача.

### 3.3. Чего не делаем

- Чанкование **на уровне материала** (перегруз для MVP; расширить потом —
  столбец в `materials` + ветка в разрешении §3.2).
- Свои embedding-модели на группу — модель глобальная (иначе векторный запрос
  надо считать несколько раз под разные модели; сложность не окупается).

## 4. Чанкеры (требования 3 и 5)

### 4.1. Интерфейс

```python
class Chunker(Protocol):
    name: str                       # «symbols», «recursive», «markdown», «by_sections»…
    def chunk(self, text: str, params: dict) -> list[Chunk]: ...
# Chunk = (content: str, meta: dict)  # meta: заголовки, границы, язык
```

### 4.2. Встроенные

| name | Логика | params |
|---|---|---|
| `whole` | Весь текст одним чанком (порог — обрезать) | `max_len` |
| `symbols` | Окно по символам с перекрытием | `size`, `overlap` |
| `recursive` | Заголовки → абзацы → предложения, слияние до size | `size`, `overlap` |
| `markdown` | По заголовкам Markdown; в meta — путь заголовков (для цитат) | `max_len`, `min_len` |

Названия/состав — уточнить при реализации; контракт один.

### 4.3. Расширяемость без пересборки (требование 5)

Два механизма, от безопасного к гибкому:

1. **Entry-points пакета (рекомендуемый)**: сторонний/свой Python-пакет
   объявляет чанкер через entry-point group `kb.rag.chunkers`. Реестр строится
   при старте worker/api (`importlib.metadata`). Установка = добавить пакет в
   образ worker/api (build-dep) и перезапустить контейнер — **без правок кода
   системы**; «пересборка системы» сводится к пересборке образа с доп. пакетом.
2. **Декларативный DSL в БД (опционально, позже)**: generic-движок интерпретирует
   JSON-правила («резать по regex», «оставлять блоки, совпавшие с паттерном»,
   «сливать до N символов»), настраивается через UI администратором — вообще
   без развертывания. Покрывает значительную часть custom-потребностей без кода.

Не делаем: исполнение произвольного Python из БД (песочница = иллюзия безопасности).

Реестр чанкеров валидируется при сохранении `rag_group_configs` (неизвестное
имя → 400 VALIDATION_ERROR со списком доступных).

## 5. Конвейер индексации (Celery, LLD §9)

```
событие: изменение text_content / новая версия / смена конфига группы
  → rag_state='pending', rag_stale=true
  → задача rag.index_material(material_id):
      1. разрешить конфиг (§3.2)          4. embedding-вызов пачками (§6)
      2. взять текущую версию + текст     5. DELETE старых чанков версии
      3. чанкер.chunk(text, params)       6. INSERT чанков с векторами
                                          7. rag_state='indexed', rag_stale=false
ретраи: экспоненциально (§9 LLD); состояние — rag_state/error_count
beat: rag.reconcile (ежечасно) — материалы с rag_stale/несоответствием
      content_hash/модели → переиндексация; отчёт в system_tasks
```

Точки вызова: после коммита версии/изменения text_content (тот же хук, что
FTS-индексация, §6.4/§7.2 LLD); после сохранения конфига группы — постановка
`rag.reindex_group_subtree` для наследующих поддеревьев. Экономия embedding-API:
индексировать **все статусы** (права всё равно фильтруют выдачу), но
переиндексировать только при фактическом изменении текста (content_hash).

## 6. Embedding-модель (требование 1)

OpenAI-совместимый `/v1/embeddings` (протестировано с: OpenAI, vLLM, Ollama,
Azure OpenAI — совместимость обязательна, конкретный поставщик значения не имеет):

```python
POST {RAG_EMBEDDING_BASE_URL}/embeddings
Authorization: Bearer {RAG_EMBEDDING_API_KEY}
{"model": RAG_EMBEDDING_MODEL, "input": ["чанк1", "чанк2", …]}   # пачки по 32–64
```

- Конфиг: `RAG_EMBEDDING_BASE_URL`, `RAG_EMBEDDING_API_KEY`, `RAG_EMBEDDING_MODEL`,
  `RAG_EMBEDDING_DIM` (размерность = столбцу), `RAG_EMBEDDING_TIMEOUT`.
- Ретраи/таймаут — те же правила, что для Gotenberg/SMTP (LLD §9).
- СА-эндпоинт `POST /admin/rag/test-connection` — проверка доступности и
  размерности до включения индексации.
- Модель хранится в каждом чанке (`embedding_model`) — свёрка находит чанки
  чужой модели.

## 7. Поиск и права (требования 2 и 6)

### 7.1. Эндпоинты

1. **`GET /search?search_type=vector|hybrid`** — штатный глобальный поиск
   (FR-133: значения зарезервированы CONCEPT §9.8 — реализуем именно их),
   все существующие фильтры (группа, тип, статус, атрибуты, теги…) работают.
   Выдача — материалы (как сейчас), ранжирование векторное/гибридное.
2. **`POST /rag/retrieve`** — для RAG-консюмеров (и будущего MCP, CONCEPT 10.4):
   возвращает **чанки** с оценками и ссылками на материалы
   `{query, group_id?, include_subgroups?, k, mode}` →
   `[{content, meta, score, material:{id,name,group_id,version}, deep_link}]`.

### 7.2. Фильтр группы (требование 2)

Как в FTS-поиске: `groups.path LIKE '<путь_группы>%'` при `include_subgroups=true`
или строго `group_id = X` при false. Поиск «в вышестоящей группе» — это и есть
поиск по её path-префиксу: поддерево целиком, накладных расходов нет
(индекс по `groups.path` существует). Денормализованный `rag_chunks.group_id`
+ JOIN materials по группе — фильтр до векторного ранжирования.

### 7.3. Права (требование 6) — главная развилка дизайна

Применяется **ровно предикат §3.2** (`visible_materials_condition`):

```sql
SELECT c.*, c.embedding <=> :query_vec AS dist
FROM rag_chunks c
JOIN materials m  ON m.id = c.material_id AND m.is_deleted = false
JOIN groups   mg ON mg.id = m.group_id
WHERE <visible_materials_condition(user, 'view', m, mg)>   -- тот же предикат
  AND <фильтр группы §7.2>
ORDER BY c.embedding <=> :query_vec
LIMIT :k;
```

- `search_type=vector`: чистый векторный порядок. `hybrid`: RRF-слияние
  FTS-ранка (существующая ветка) и векторной дистанции, оба потока уже
  право-фильтрованы.
- Масштаб 10k материалов: даже полный перебор с фильтром ~ единицы мс;
  HNSW включаем, отфильтрованный поиск — iterative scan (pgvector ≥ 0.8);
  параметр `ef_search` — реестр настроек.
- Подпись «на чанке X материала Y» сопровождается проверкой прав на сам
  материал в момент выдачи (предикат уже в запросе) — утечка запрещённого
  контента через чанки невозможна по построению.

## 8. План внедрения (предложение, этапы шага [7])

| # | Содержание | Приёмка |
|---|---|---|
| 1 | Схема (0011) + реестр чанкеров + встроенные чанкеры + конфиг групп (API СА) + ручная переиндексация | юнит-тесты чанкеров; CRUD конфигов |
| 2 | Конвейер (Celery): хуки на версии/текст, embedding-клиент, reconcile | интеграционный тест: публикация → чанки с векторами |
| 3 | `search_type=vector|hybrid` + `POST /rag/retrieve` (предикат прав) | API-тесты: права deny/SA/черновики; фильтр группы |
| 4 | UI: переключатель режима поиска; СА-экран настройки чанкования групп; статус индексации | сценарий по аналогии US-034/048 |
| 5 | (опционально) MCP-сервер read-only поверх `/rag/retrieve` + REST | — |

## 9. Открытые вопросы — РЕШЕНЫ (согласовано с заказчиком, 10.11.2026)

1. Размерность/модель: **одна на систему** — `KB_RAG_EMBEDDING_MODEL` +
   `KB_RAG_EMBEDDING_DIM` (env, дефолт 1536); смена = миграция + полный
   переиндекс (§3.3). Сверка модели — в каждом чанке (`embedding_model`).
2. Непубликованные статусы: **индексируются все статусы** — права фильтруют
   выдачу (предикат §3.2 в запросе, §7.3); расход embedding-API принят.
3. Гибрид: **RRF** (score = Σ 1/(60+rank), ранки с 1 в каждом потоке) —
   без калибровки шкал; оба потока право-фильтрованы.
4. Дедупликация: **один лучший чанк на материал** в `/rag/retrieve`
   (DISTINCT ON material_id; разнообразие источников в top-k).
5. Лимиты: **k ≤ 20** (валидация тела), вызовы — в `search_events`
   (аналитика §7.6 переиспользуется, без ПДн); rate limit на MVP не нужен —
   аутентификация обязательна (внешние консюмеры — шаг 5, MCP read-only).

---

## Приложение А. Пример entry-point чанкера (к §4.3)

Механизм: система не импортирует плагин напрямую — при старте она опрашивает
`importlib.metadata.entry_points(group="kb.rag.chunkers")`: какие **установленные
в окружении пакеты** объявили себя чанкерами. Объявление живёт в метаданных
пакета (pyproject), конфигов и списков плагинов в системе нет.

### А.1. Сторона системы — контракт и реестр

```python
# backend/app/rag/base.py — контракт (плагин систему НЕ импортирует: duck typing)
from dataclasses import dataclass, field

@dataclass
class Chunk:
    content: str
    meta: dict = field(default_factory=dict)   # заголовки, смещения, язык…

class Chunker(Protocol):
    name: str
    def chunk(self, text: str, params: dict) -> list[Chunk]: ...
```

```python
# backend/app/rag/registry.py — строится один раз при старте api/worker
import logging
from importlib.metadata import entry_points

from app.rag.chunkers import (WholeChunker, SymbolsChunker,
                              RecursiveChunker, MarkdownChunker)

log = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "kb.rag.chunkers"          # ← имя-договорённость

def build_registry() -> dict[str, Chunker]:
    reg: dict[str, Chunker] = {}
    for cls in (WholeChunker, SymbolsChunker, RecursiveChunker, MarkdownChunker):
        reg[cls.name] = cls()                                   # встроенные
    for ep in entry_points(group=ENTRY_POINT_GROUP):            # ← внешние пакеты
        try:
            obj = ep.load()                                     # импорт класса из пакета
            name = getattr(obj, "name", ep.name)
            if name in reg:
                log.warning("чанкер %s: дубль, пропущен", name)
                continue
            if not callable(getattr(obj, "chunk", None)):
                raise TypeError("нет метода chunk(text, params)")
            reg[name] = obj
        except Exception:
            log.exception("чанкер %s не загрузился", ep.value)  # битый плагин не валит старт
    return reg

_REGISTRY: dict[str, Chunker] | None = None

def get_registry() -> dict[str, Chunker]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry()
    return _REGISTRY
```

### А.2. Сторона плагина — отдельный пакет

```
kb-chunker-gost/
├── pyproject.toml
└── kb_chunker_gost/
    └── __init__.py
```

```toml
# pyproject.toml — вся интеграция с системой в этих трёх строках
[project]
name = "kb-chunker-gost"
version = "0.1.0"

[project.entry-points."kb.rag.chunkers"]
gost_sections = "kb_chunker_gost:GostSectionsChunker"
```

```python
# kb_chunker_gost/__init__.py — чанкер регламентов: нумерованные разделы + приложения
import re
from dataclasses import dataclass, field

@dataclass
class Chunk:
    content: str
    meta: dict = field(default_factory=dict)

class GostSectionsChunker:
    name = "gost_sections"
    _HDR = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+\S|Приложение\s+[А-Я])", re.M)

    def chunk(self, text: str, params: dict) -> list[Chunk]:
        max_len = int(params.get("max_len", 2000))
        hits = list(self._HDR.finditer(text))
        if not hits:
            return [Chunk(text[:max_len], {"chunker": self.name})]
        out = []
        for i, h in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
            out.append(Chunk(text[h.start():end].strip()[:max_len], {
                "chunker": self.name, "section": h.group(0).strip(), "offset": h.start(),
            }))
        return out
```

### А.3. Подключение

Способ 1 (рекомендуемый, детерминированный): пакет — зависимость образов
api/worker, одна строка в `backend/pyproject.toml`:

```toml
dependencies = [
  # …существующие…
  "kb-chunker-gost @ git+https://git.internal/kb/kb-chunker-gost.git@v0.1.0",
]
```

`docker compose build api worker` → перезапуск. Изменений в коде системы нет —
меняется только окружение.

Способ 2 (экспериментальный, без пересборки образа): entrypoint при флаге
`KB_PLUGINS=1` ставит `pip install --no-cache-dir /opt/plugins/*.whl` из
примонтированного каталога перед стартом uvicorn/celery. Минусы: зависимость
старта от сети, невоспроизводимость. Для продуктива — способ 1.

### А.4. Рантайм

1. Старт → `get_registry()` → `{whole, symbols, recursive, markdown, gost_sections}`.
2. СА: `PUT /admin/rag/groups/{id}/config` `{"chunker": "gost_sections",
   "params": {"max_len": 1500}}` — сохранение валидируется по реестру
   (неизвестное имя → 400 + список доступных).
3. `rag.index_material` разрешает конфиг по цепочке групп (§3.2), берёт
   `registry["gost_sections"]`, вызывает `.chunk(text, params)`. Конвейер
   про ГОСТ ничего не знает — только контракт.

Итог по требованию 5: новый режим чанкования = маленький автономный пакет
(тестируется pytest'ом без системы), подключаемый строкой зависимости;
реестр/конфигурация/конвейер/переиндексация уже существуют в системе.
