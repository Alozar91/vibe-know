// Административные API (только СА): снапшоты прав, роли, матрица переходов,
// триггеры уведомлений, аудит, параметры системы, служебный раздел, RAG.
import { api } from './client'
import type { Material, Role, Snapshot } from '../shared/types'

// ---------- снапшоты прав (US-044, FR-102/105) ----------

/** GET /{groups|materials}/{id}/permissions — снапшоты объекта. */
export function getPermissions(objectType: 'group' | 'material', objectId: string): Promise<Snapshot[]> {
  return api<Snapshot[]>(`/${objectType}s/${objectId}/permissions`)
}

/** POST /{groups|materials}/{id}/permissions — копия шаблона роли (US-044 ш.1). */
export function copyRolePermissions(objectType: 'group' | 'material', objectId: string, roleId: string): Promise<unknown> {
  return api(`/${objectType}s/${objectId}/permissions`, {
    method: 'POST',
    body: JSON.stringify({ role_id: roleId, entries: [] }),
  })
}

/** PATCH /permissions/snapshots/{id} — allow/deny/unset (FR-102). */
export function setPermissionState(snapshotId: string, permission: string, state: 'allow' | 'deny' | 'unset'): Promise<unknown> {
  return api(`/permissions/snapshots/${snapshotId}`, {
    method: 'PATCH',
    body: JSON.stringify({ entries: [{ permission, state }] }),
  })
}

/** DELETE /permissions/snapshots/{id} — удаление снапшота. */
export function deletePermissionSnapshot(snapshotId: string): Promise<void> {
  return api<void>(`/permissions/snapshots/${snapshotId}`, { method: 'DELETE' })
}

/** GET /roles — роли-шаблоны. */
export function getRoles(): Promise<Role[]> {
  return api<Role[] | { items: Role[] }>('/roles').then((r) => Array.isArray(r) ? r : r.items)
}

// ---------- матрица переходов (US-046, FR-070/073/074) ----------

export interface TransitionRule {
  id: string
  from_status: Material['status'] | null
  to_status: Material['status']
  is_protected: boolean
  permissions: string[]
}

/** GET /transition-rules. */
export function getTransitionRules(): Promise<TransitionRule[]> {
  return api<TransitionRule[]>('/transition-rules')
}

/** PATCH /transition-rules/{id} — права перехода (достаточно любого, FR-070). */
export function updateTransitionRule(id: string, permissions: string[]): Promise<TransitionRule> {
  return api<TransitionRule>(`/transition-rules/${id}`, {
    method: 'PATCH', body: JSON.stringify({ permissions }),
  })
}

/** DELETE /transition-rules/{id} — удаление незащищённого (FR-073). */
export function deleteTransitionRule(id: string): Promise<void> {
  return api<void>(`/transition-rules/${id}`, { method: 'DELETE' })
}

/** POST /transition-rules — новое правило (from_status null = «*»). */
export function createTransitionRule(body: {
  from_status: string | null
  to_status: string
  permissions: string[]
}): Promise<unknown> {
  return api('/transition-rules', { method: 'POST', body: JSON.stringify(body) })
}

// ---------- триггеры уведомлений (US-047, FR-134/135) ----------

export interface RecipientCfg {
  type: string
  role_id?: string
  permission?: string
  scope?: string
}

export interface Trigger {
  event_type: string
  enabled: boolean
  recipients: RecipientCfg[]
}

/** GET /notification-triggers. */
export function getNotificationTriggers(): Promise<Trigger[]> {
  return api<Trigger[]>('/notification-triggers')
}

/** PUT /notification-triggers/{event} — включение/отключение (аудит FR-140). */
export function updateNotificationTrigger(eventType: string, body: {
  enabled: boolean
  recipients: RecipientCfg[]
}): Promise<unknown> {
  return api(`/notification-triggers/${eventType}`, {
    method: 'PUT', body: JSON.stringify(body),
  })
}

// ---------- аудит (US-049, FR-140–143) ----------

export interface AuditRow {
  id: number
  occurred_at: string | null
  actor_user_id: string | null
  actor_display_name: string | null
  actor_is_service: boolean
  action: string
  object_type: string
  object_id: string | null
  details: Record<string, unknown>
}

/** GET /audit — журнал (FR-140). */
export function listAudit(page: number, action: string, objectType: string):
  Promise<{ items: AuditRow[]; total: number }> {
  const qs = new URLSearchParams({ page: String(page), per_page: '50' })
  if (action) qs.set('action', action)
  if (objectType) qs.set('object_type', objectType)
  return api<{ items: AuditRow[]; total: number }>(`/audit?${qs}`)
}

/** GET /audit/export — выгрузка NDJSON (FR-143): fetch+blob с Bearer (см. apiDownload). */
export function exportAuditNdjson(action: string, objectType: string): Promise<Response> {
  const qs = new URLSearchParams()
  if (action) qs.set('action', action)
  if (objectType) qs.set('object_type', objectType)
  return fetch(`/api/v1/audit/export?${qs}`, {
    headers: { Authorization: `Bearer ${getAccessTokenForExport()}` },
  })
}

// Локальный доступ к токену для экспорта NDJSON (не через apiDownload —
// выгрузка не JSON, а Response-стрим); импорт в конце файла — ниже использования.
import { getAccessToken } from '../shared/auth/auth'
function getAccessTokenForExport(): string {
  const t = getAccessToken()
  if (!t) throw new Error('Не выполнен вход')
  return t
}

// ---------- параметры системы (US-048, NFR-020) ----------

export interface Setting {
  key: string
  value: unknown
  description: string | null
  updated_at: string | null
}

/** GET /settings — реестр system_settings §2.5. */
export function getSettings(): Promise<Setting[]> {
  return api<Setting[]>('/settings')
}

/** PUT /settings/{key} — изменение (jsonb; аудит FR-140). */
export function updateSetting(key: string, value: unknown): Promise<unknown> {
  return api(`/settings/${key}`, { method: 'PUT', body: JSON.stringify({ value }) })
}

// ---------- служебный раздел (US-050, FR-012/021/090; NFR-014) ----------

export interface ServiceTask {
  id: string
  task_type: string
  payload: Record<string, unknown>
  state: string
  created_at: string | null
  closed_at: string | null
}

export interface TasksSummary {
  summary: Record<string, Record<string, number>>
  items: Array<{
    id: string
    task_type: string
    object_type: string | null
    object_id: string | null
    state: string
    attempts: number
    last_error: string | null
    scheduled_at: string | null
    finished_at: string | null
  }>
}

/** GET /service-tasks — задачи передачи права ревью (FR-012). */
export function getServiceTasks(all: boolean): Promise<ServiceTask[]> {
  return api<ServiceTask[]>(`/service-tasks${all ? '?all=true' : ''}`)
}

/** POST /service-tasks/{id}:close — закрытие (US-004 ш.5). */
export function closeServiceTask(id: string): Promise<void> {
  return api<void>(`/service-tasks/${id}:close`, { method: 'POST' })
}

/** GET /tasks — состояние фоновых задач (NFR-014). */
export function getTasksSummary(): Promise<TasksSummary> {
  return api<TasksSummary>('/tasks')
}

// ---------- RAG (пост-MVP, RAG_DESIGN §8-4) ----------

export interface RagConfigOut {
  group_id: string
  chunkers: string[]
  own: { chunker: string; params: Record<string, unknown>; enabled: boolean } | null
  effective: { chunker: string; params: Record<string, unknown>; enabled: boolean } | null
  inherit_from: string | null
}

export interface RagStatus {
  counts: Record<string, number>
  problems: { id: string; name: string; state: string; stale: boolean; updated_at: string | null }[]
  total_chunks: number
}

/** GET /admin/rag/status — статус индексации (§8-4). */
export function getRagStatus(): Promise<RagStatus> {
  return api<RagStatus>('/admin/rag/status')
}

/** POST /admin/rag/materials/{id}:reindex — переиндексация материала. */
export function reindexMaterial(id: string): Promise<void> {
  return api<void>(`/admin/rag/materials/${id}:reindex`, { method: 'POST' })
}

/** GET /admin/rag/groups/{id}/config — конфигурация чанкования группы (§3). */
export function getRagGroupConfig(groupId: string): Promise<RagConfigOut> {
  return api<RagConfigOut>(`/admin/rag/groups/${groupId}/config`)
}

/** PUT /admin/rag/groups/{id}/config — сохранение конфигурации (аудит rag.group_config). */
export function updateRagGroupConfig(groupId: string, body: {
  chunker: string
  params: Record<string, unknown>
  enabled: boolean
}): Promise<unknown> {
  return api(`/admin/rag/groups/${groupId}/config`, { method: 'PUT', body: JSON.stringify(body) })
}

/** DELETE /admin/rag/groups/{id}/config — снять явную настройку (наследование §3.2). */
export function deleteRagGroupConfig(groupId: string): Promise<void> {
  return api<void>(`/admin/rag/groups/${groupId}/config`, { method: 'DELETE' })
}

/** POST /admin/rag/groups/{id}:reindex — переиндексация поддерева. */
export function reindexGroupSubtree(groupId: string): Promise<void> {
  return api<void>(`/admin/rag/groups/${groupId}:reindex`, { method: 'POST' })
}

/** POST /admin/rag/test-connection — проверка embedding-провайдера (§6). */
export function testRagConnection(): Promise<{ model: string; dim: number }> {
  return api<{ model: string; dim: number }>('/admin/rag/test-connection', { method: 'POST' })
}
