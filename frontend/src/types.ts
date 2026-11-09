// Типы API (LLD §12; соответствие use_cases/materials/dto.py и groups).
export interface Page<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

export interface GroupNode {
  id: string
  name: string
  parent_id: string | null
  path: string
  children?: GroupNode[]
}

export interface MaterialType {
  id: string
  name: string
}

export interface Material {
  id: string
  group_id: string
  name: string
  type_id: string
  status: 'draft' | 'in_review' | 'approved' | 'published' | 'archived'
  author_id: string
  version: number
  is_deleted: boolean
  updated_at?: string
  published_at?: string
}

export interface MaterialCard extends Material {
  type_name?: string
  text_content: string | null
  text_out_of_sync: boolean
  current_file_id: string | null
  created_at?: string
  attributes: MaterialAttribute[]
  tag_ids: string[]
  permissions: Record<string, boolean> // FR-129: карта прав пользователя
}

export interface MaterialAttribute {
  attribute_id: string
  name: string
  value_type: 'string' | 'number' | 'date' | 'url' | 'dictionary'
  is_multivalue: boolean
  is_required: boolean
  readonly: boolean // «осиротевшие» (FR-051)
  values: string[]
}

export interface Role {
  id: string
  name: string
  is_virtual_all_users: boolean
  permissions: string[]
}

export interface Snapshot {
  id: string
  object_type: 'group' | 'material'
  object_id: string
  role_id: string | null
  role_name: string
  entries: { permission: string; state: 'allow' | 'deny' }[]
}

// Этап 5: жизненный цикл (§4.1, FR-070)
export interface TransitionInfo {
  id: string
  from_status: Material['status'] | null // null = «*»
  to_status: Material['status']
  is_protected: boolean
  permissions: string[]
  allowed: boolean
  need_cascade: boolean
  children_count: number
}

export interface StatusLogEntry {
  from_status: Material['status'] | null
  to_status: Material['status']
  user_id: string
  user_display_name: string
  created_at: string
}

export const STATUS_RU: Record<Material['status'], string> = {
  draft: 'Черновик',
  in_review: 'На проверке',
  approved: 'Утверждён',
  published: 'Публикация',
  archived: 'Архив',
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }) // NFR-018: часовой пояс браузера
}
