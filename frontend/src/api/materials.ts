// Материалы: карточка, CRUD, жизненный цикл, файлы, версии, связи, комментарии.
// Трассировки FR/US — в комментариях функций (соответствие LLD §12.3).
import { api, apiDownload, apiUpload } from './client'
import type {
  CommentInfo, FileState, GroupNode, Material, MaterialCard,
  Page, StatusLogEntry, TransitionInfo, VersionDiff, VersionInfo,
} from '../shared/types'

// ---------- чтение ----------

/** GET /materials — список с фильтрами (US-005, FR-103/117/121; разделы FR-123–125). */
export function listMaterials(query: string): Promise<Page<Material>> {
  return api<Page<Material>>(`/materials${query}`)
}

/** GET /materials/deleted — удалённые (US-050). */
export function listDeletedMaterials(): Promise<(Material & { deleted_at: string | null })[]> {
  return api<{ items: (Material & { deleted_at: string | null })[]; total: number }>('/materials/deleted')
    .then((r) => r.items)
}

/** GET /materials/{id} — карточка (US-037, FR-129). */
export function getMaterial(id: string): Promise<MaterialCard> {
  return api<MaterialCard>(`/materials/${id}`)
}

/** GET /materials/{id}/transitions — доступные переходы (FR-070). */
export function getTransitions(id: string): Promise<TransitionInfo[]> {
  return api<TransitionInfo[]>(`/materials/${id}/transitions`)
}

/** GET /materials/{id}/status-log — журнал статусов (FR-075). */
export function getStatusLog(id: string): Promise<StatusLogEntry[]> {
  return api<StatusLogEntry[]>(`/materials/${id}/status-log`)
}

/** GET /materials/{id}/file-state — состояние конвейера (US-011/012). */
export function getFileState(id: string): Promise<FileState> {
  return api<FileState>(`/materials/${id}/file-state`)
}

/** GET /materials/{id}/versions — список версий (FR-145). */
export function getVersions(id: string): Promise<VersionInfo[]> {
  return api<{ items: VersionInfo[] }>(`/materials/${id}/versions`).then((r) => r.items)
}

/** GET /materials/{id}/versions/{n}/diff — diff соседних версий (US-041). */
export function getVersionDiff(id: string, n: number): Promise<VersionDiff> {
  return api<VersionDiff>(`/materials/${id}/versions/${n}/diff`)
}

/** GET /materials/{id}/comments — комментарии (US-038). */
export function getComments(id: string): Promise<CommentInfo[]> {
  return api<{ items: CommentInfo[] }>(`/materials/${id}/comments`).then((r) => r.items)
}

// ---------- мутации (If-Match — оптимистичная блокировка FR-094/095) ----------

/** POST /materials — создание (US-007, FR-048/052). */
export function createMaterial(body: {
  name: string
  group_id: string
  type_id: string
  text_content: string | null
  attribute_values: { attribute_id: string; values: unknown[] }[]
  tag_ids: string[]
}): Promise<{ id: string }> {
  return api<{ id: string }>('/materials', { method: 'POST', body: JSON.stringify(body) })
}

/** PATCH /materials/{id} — правка с If-Match (FR-095). */
export function updateMaterial(id: string, version: number, body: {
  name?: string
  text_content?: string | null
}): Promise<unknown> {
  return api(`/materials/${id}`, {
    method: 'PATCH',
    headers: { 'If-Match': String(version) },
    body: JSON.stringify(body),
  })
}

/** DELETE /materials/{id} — удаление с If-Match (FR-090). */
export function deleteMaterial(id: string, version: number): Promise<void> {
  return api<void>(`/materials/${id}`, {
    method: 'DELETE',
    headers: { 'If-Match': String(version) },
  })
}

/** POST /materials/{id}/transitions — переход статуса (US-015–021). */
export function postTransition(id: string, version: number, body: {
  to_status: string
  confirm_cascade: boolean
}): Promise<unknown> {
  return api(`/materials/${id}/transitions`, {
    method: 'POST',
    headers: { 'If-Match': String(version) },
    body: JSON.stringify(body),
  })
}

/** POST /materials/{id}/versions/{n}/restore — восстановление версии (US-042). */
export function restoreVersion(id: string, n: number, version: number): Promise<unknown> {
  return api(`/materials/${id}/versions/${n}/restore`, {
    method: 'POST',
    headers: { 'If-Match': String(version) },
  })
}

// ---------- файл (§6.2, §6.4) ----------

export interface FileUploadResult {
  file_state: FileState
  text_filled_automatically: boolean
  offer_text_update: boolean
  text_out_of_sync: boolean
}

/** POST /materials/{id}/file — multipart-загрузка (US-008; text_update_choice — FR-030). */
export function uploadMaterialFile(id: string, file: File, textUpdateChoice?: 'replace' | 'keep'):
  Promise<FileUploadResult> {
  const query = textUpdateChoice ? `?text_update_choice=${textUpdateChoice}` : ''
  return apiUpload<FileUploadResult>(`/materials/${id}/file`, file, query)
}

/** GET /materials/{id}/file | text.md | pdf — авторизованное скачивание (US-014). */
export function downloadMaterial(kind: 'file' | 'text.md' | 'pdf', id: string): Promise<Response> {
  return apiDownload(`/materials/${id}/${kind === 'file' ? 'file' : kind}`)
}

// ---------- связи (этап 7, FR-035–037/092/126) ----------

/** POST /materials/{id}/children — создание подчинённого (US-024/025). */
export function createChild(id: string, body: {
  kind: 'adaptation' | 'translation'
  group_id: string
  name?: string
  language_id?: string
}): Promise<unknown> {
  return api(`/materials/${id}/children`, { method: 'POST', body: JSON.stringify(body) })
}

/** POST /materials/{id}/copy — копирование (US-028, FR-092). */
export function copyMaterial(id: string, body: { group_id: string; name: string }): Promise<unknown> {
  return api(`/materials/${id}/copy`, { method: 'POST', body: JSON.stringify(body) })
}

/** POST /materials/{id}/move — перемещение (US-027, FR-037). */
export function moveMaterial(id: string, body: { group_id: string }): Promise<unknown> {
  return api(`/materials/${id}/move`, { method: 'POST', body: JSON.stringify(body) })
}

/** POST /materials/{id}/master — привязка мастера (US-026, FR-036). */
export function setMaster(id: string, masterId: string): Promise<unknown> {
  return api(`/materials/${id}/master`, {
    method: 'POST', body: JSON.stringify({ master_id: masterId }),
  })
}

/** DELETE /materials/{id}/master — отвязка мастера (US-026). */
export function detachMaster(id: string): Promise<unknown> {
  return api(`/materials/${id}/master`, { method: 'DELETE' })
}

// ---------- комментарии (US-038, FR-096–098) ----------

/** POST /materials/{id}/comments — добавление комментария. */
export function addComment(id: string, text: string): Promise<unknown> {
  return api(`/materials/${id}/comments`, { method: 'POST', body: JSON.stringify({ text }) })
}

// ---------- вспомогательное для диалогов ----------

/** Группы для диалогов master/child/copy/move (FR-109: видимые группы). */
export function listGroupsForDialogs(): Promise<GroupNode[]> {
  return api<GroupNode[]>('/groups')
}
