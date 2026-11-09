# AGENTS.md

## What this repo is

MVP implementation repository for a corporate knowledge base system («Корпоративная база знаний»). Steps of the gated plan in `Docs/CONCEPT.md` §17: [1] requirements (done, customer-approved, 1.6) → [2] user scenarios (done, 0.9, seven review rounds, accepted) → [3] HLD (done, 1.1, ten review rounds, accepted) → [4] LLD (done, 0.2, two internal review rounds, accepted) → [5] MVP (in progress, started 09.11.2026): 11-stage plan — [1] foundation (docker-compose, FastAPI skeleton, Alembic, Keycloak realm, React skeleton) → [2] accounts/roles → [3] groups/dictionaries → [4] permissions/materials → [5] lifecycle → [6] files/versions → [7] master-detail → [8] search → [9] notifications → [10] CA perimeter → [11] NFR/acceptance; acceptance per US-001–055 and SCENARIOS §6. LLD is the implementation contract: table/column/task names and error codes exactly as in LLD §2, §9, §12.2; deviations from HLD mechanics as «[уточнение LLD]»; behavioral discrepancies logged as remarks in LLD «Приложение А» (16.1 if needed).

## The five documents

All content is in **Russian** — write edits and new docs in Russian, matching the formal existing style (numbered sections, tables, «История изменений» at top, dates as DD.MM.YYYY).

- `Docs/CONCEPT.md` — source of truth: domain model, roles, lifecycle, permissions, search, notifications. Terminology must match the glossary (§18).
- `Docs/REQUIREMENTS.md` — FR-001–152 / NFR-001–022, with traceability to CONCEPT sections (§8).
- `Docs/SCENARIOS.md` — US-001–055 acceptance scenarios + coverage matrix «FR → US» (§5), раздел 6 — сквозные проверки.
- `Docs/HLD.md` — high-level architecture (accepted, 1.1). Architecture decisions that bind documents go to CONCEPT 16.1; intra-system design decisions stay in HLD. §4 is the authoritative source for software versions (PostgreSQL 18, Keycloak 26.x, Valkey 9.1, Silo, Gotenberg, Python 3.15, FastAPI, Celery, React 19/Node 26 LTS, nginx 1.30, Prometheus 3).
- `Docs/LLD.md` — detailed design (accepted, 0.2): data model (§2), permission predicate SQL (§3.2), lifecycle validators, versioning, CAS keys in silo, FTS vector, notification pipeline (§6), queue/task contracts (§9), Keycloak integration (§8), API endpoints (§12) and error codes (§12.2). Deviations from HLD mechanics are marked «[уточнение LLD]» (NOTIFY/LISTEN cache invalidation, Keycloak full-dump sync, users.email_cache). LLD review may trigger sync edits in HLD/REQUIREMENTS/CONCEPT/SCENARIOS.

## MVP implementation (step [5])

- Monorepo in this same repo: `backend/` (FastAPI + uv), `frontend/` (React/Vite), `deploy/` (docker-compose); git branch `mvp` with per-stage feature branches `mvp-etap-N` (ref names `mvp/etap-N` are impossible while branch `mvp` exists), PR-style into `mvp`.
- Follow the 11-stage plan approved by the user; implement a stage only after the previous stage's US acceptance. Do not jump ahead or start post-MVP items (CONCEPT §15.3).
- Tests: pytest per stage (unit tests for key logic + API tests per US scenario).
- `C:\Users\SeregaPC\.opencode\plan\mvp-plan.md` (outside the repo) is the working plan — never commit it.
- Open LLD §14 questions are resolved inside the stages: cache thresholds → stage 4; «Язык» dictionary → stage 3 (deployment step [6] seeds it); Gotenberg/SMTP retries → stages 6/9.

## Cross-document sync (the main way to get this wrong)

A behavioral change is never made in one file. One decision typically requires synchronized edits across the docs:

1. `CONCEPT.md` — the rule itself (§4–13) + «История изменений» row; significant decisions also get a 16.1 entry.
2. `REQUIREMENTS.md` — affected FR/NFR rows + history + traceability §8.
3. `SCENARIOS.md` — affected US scenarios + coverage matrix §5 + history + «Приложение А».
4. `HLD.md` / `LLD.md` — only when the change touches architecture or detailed design; LLD deviates from HLD mechanics via «[уточнение LLD]».

## Decision and versioning conventions

- Significant decisions get a numbered entry in `CONCEPT.md` §16.1, referenced everywhere as «16.1-xx». Small interpretations in REQUIREMENTS are marked «[уточнение]» instead of changing concept decisions.
- Discrepancies found in review are logged as remarks; the concept changes only via §16.1 (REQUIREMENTS §7, SCENARIOS §7). Accepted scenario-review remarks are recorded per round in SCENARIOS «Приложение А».
- Every doc has a top «История изменений» table — append a row for each substantive edit: version, date, summary (which review round, which remarks/decisions). Statuses: «актуальная редакция» vs «черновик для ревью». Version tracks: CONCEPT 2.x, REQUIREMENTS 1.x, SCENARIOS 0.x, HLD 1.x (review rounds), LLD 0.x.
- IDs (FR-xxx, NFR-xxx, US-xxx) are stable: reword in place, never renumber; new items get the next free number. Renumbering breaks the traceability matrix (REQUIREMENTS §8, SCENARIOS §5).
- Cross-reference notation: `(4.1)` = CONCEPT section, `(FR-xxx)`/`(NFR-xxx)` = REQUIREMENTS, `(US-xxx)` = SCENARIOS, `(16.1-xx)` = concept decision.

## Scope discipline

MVP only. Post-MVP ideas go to the registry in CONCEPT §15.3, not into requirements. REQUIREMENTS §6 lists explicit non-goals — don't reintroduce them.

## Verification

Docs: self-verify consistency after edits — every FR you touched still maps to a US in the SCENARIOS matrix (or SCENARIOS §6), REQUIREMENTS §8 traceability matches CONCEPT sections, and all touched «История изменений» tables are updated. Version/date references in doc preambles (e.g. LLD §1 «Входные документы: … ред. …») must match the actual current versions of the other docs.

Code: pytest per stage; API acceptance against SCENARIOS US steps. `docker compose up` from `deploy/` must bring the full stack up healthy (stage 1 acceptance).

## Repo quirks

- `.kilo/kilo.jsonc` contains API keys and is intentionally gitignored — never commit it or reproduce its contents.
- Docker Desktop on this machine lives at `C:\Program Files\Docker\Docker\Docker Desktop.exe` (not LOCALAPPDATA); start it manually before compose work — the daemon takes ~1 min to come up. WSL2 distro: Ubuntu, WSL version 2.
- Local toolchain: uv 0.11.x, Node 24 LTS (npm 10.x), Python 3.15 — HLD §4 container versions still govern; local versions only for dev ergonomics.
- Main branch is `master` (no `main`); `docs` branch is a stale copy of the same commit.
- Compose gotchas (discovered stage 1): host port 8000 is occupied by a foreign process → api is mapped to 8001; `minio/mc` is gone from Docker Hub → use `pgsty/mc`; postgres 18 mounts at `/var/lib/postgresql` (not `.../data`); Gotenberg image has no wget/curl (healthcheck = `kill -0 1`); Keycloak has no curl (healthcheck = /dev/tcp probe of mgmt 9000); realm import skips silently if realm already exists in DB (change passwords → `docker compose down -v` or kcadm `set-password`); realm JSON field names are strict (`resetPasswordAllowed`, no `maxTemporaryLockoutMinutes`); realm `passwordPolicy` applies to imported seed users' passwords.
- Celery child process in kb-worker may hang silently (task logged as "received" but never succeeds; dispatch stalls, events stay `processed=false`) → `docker compose restart worker` fixes it (seen stage 9 twice). Also: worker container command must run beat — it is embedded via `--beat` in `app/worker/main.py` (without it schedules silently never fire).

## Maintenance

- This file must be kept current: when a session discovers a new durable convention, gotcha, or decision workflow, add it here in the same session — one bullet, only if a future session would likely miss it.
- Do not log one-off task details, current statuses, or work in progress here; that belongs in the docs' «История изменений» tables.
