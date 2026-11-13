// Группы: дерево, CRUD (US-052), удалённые (US-050). LLD §12.3.
import { api } from './client'
import type { GroupNode } from '../shared/types'

/** GET /groups — дерево видимых групп (FR-016/109). */
export function getGroupTree(): Promise<GroupNode[]> {
  return api<GroupNode[]>('/groups')
}

/** POST /groups — создание (FR-017). */
export function createGroup(body: { name: string; parent_id: string | null }): Promise<unknown> {
  return api('/groups', { method: 'POST', body: JSON.stringify(body) })
}

/** PATCH /groups/{id} — переименование (FR-017). */
export function renameGroup(id: string, name: string): Promise<unknown> {
  return api(`/groups/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) })
}

/** DELETE /groups/{id}?confirm_rights= — удаление (FR-018/019/020; RIGHTS_CONFIRM_REQUIRED). */
export function deleteGroup(id: string, confirmRights: boolean):
  Promise<{ mode: 'hard' | 'soft'; subtree_count: number }> {
  return api<{ mode: 'hard' | 'soft'; subtree_count: number }>(
    `/groups/${id}${confirmRights ? '?confirm_rights=true' : ''}`,
    { method: 'DELETE' },
  )
}

/** GET /groups/deleted — удалённые ветки (US-050). */
export function listDeletedGroups(): Promise<(GroupNode & { deleted_at: string | null })[]> {
  return api<(GroupNode & { deleted_at: string | null })[]>('/groups/deleted')
}
