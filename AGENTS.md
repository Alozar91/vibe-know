# AGENTS.md

## What this repo is

Specification-only repository for a corporate knowledge base system («Корпоративная база знаний»). **There is no code, build, or CI.** Work follows the gated plan in `Docs/CONCEPT.md` §17: [1] requirements (done, customer-approved) → [2] user scenarios (draft under review, 0.9 after seven review rounds) → [3] HLD (done, 1.1 after ten review rounds) → [4] LLD (draft under review, 0.2 after two internal review rounds; customer review not yet done) → [5] MVP (not started). Don't create code scaffolding unless the user explicitly starts a later step.

## The five documents

All content is in **Russian** — write edits and new docs in Russian, matching the formal existing style (numbered sections, tables, «История изменений» at top, dates as DD.MM.YYYY).

- `Docs/CONCEPT.md` — source of truth: domain model, roles, lifecycle, permissions, search, notifications. Terminology must match the glossary (§18).
- `Docs/REQUIREMENTS.md` — FR-001–152 / NFR-001–022, with traceability to CONCEPT sections (§8).
- `Docs/SCENARIOS.md` — US-001–055 acceptance scenarios + coverage matrix «FR → US» (§5).
- `Docs/HLD.md` — high-level architecture (step [3], version 1.x, draft under review). Architecture decisions that bind documents go to CONCEPT 16.1; intra-system design decisions stay in HLD. On HLD review rounds: its «Приложение А» logs remarks; sync CONCEPT/REQUIREMENTS only when a rule or FR/NFR is affected.
- `Docs/LLD.md` — detailed design (step [4], version 0.x, draft under review): data model, permission predicate SQL, lifecycle validators, versioning, CAS keys in silo, FTS vector, notification pipeline, queue contracts, Keycloak integration, API error codes and endpoint list. Closes HLD §12 open questions (its §13 maps №1–8 to LLD sections); has own «Приложение А» for review remarks; marks deviations from HLD mechanics as «[уточнение LLD]» (so far: NOTIFY/LISTEN cache invalidation, Keycloak full-dump sync, users.email_cache). LLD review may trigger sync edits in HLD/REQUIREMENTS/CONCEPT/SCENARIOS (example: remark №5 → 16.1-119 email_cache, synced HLD 1.1 / REQUIREMENTS 1.6 / CONCEPT 2.17 / SCENARIOS 0.9).

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

No automated checks exist. After edits, self-verify consistency: every FR you touched still maps to a US in the SCENARIOS matrix (or SCENARIOS §6), REQUIREMENTS §8 traceability matches CONCEPT sections, and all touched «История изменений» tables are updated. Version/date references in doc preambles (e.g. LLD §1 «Входные документы: … ред. …») must match the actual current versions of the other docs.

## Repo quirks

- `.kilo/kilo.jsonc` contains API keys and is intentionally gitignored — never commit it or reproduce its contents.

## Maintenance

- This file must be kept current: when a session discovers a new durable convention, gotcha, or decision workflow, add it here in the same session — one bullet, only if a future session would likely miss it.
- Do not log one-off task details, current statuses, or work in progress here; that belongs in the docs' «История изменений» tables.
