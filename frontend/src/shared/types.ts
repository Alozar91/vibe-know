// Типы API (LLD §12; соответствие use_cases/materials/dto.py и groups).
// Реорганизация frontend: только DTO — русские словари и утилиты в shared/lib.
export interface Page<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

export interface DictionaryInfo {
  id: string
  name: string
  values: string[]
  value_items: { id: string; value: string }[]
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
  /** Атрибуты типа (GET /types, FR-043); dictionary-атрибут несёт dictionary_id. */
  attributes?: TypeAttr[]
}

/** Атрибут типа материала (FR-044) — для форм создания/редактирования. */
export interface TypeAttr {
  id: string
  name: string
  value_type: 'string' | 'number' | 'date' | 'url' | 'dictionary'
  is_multivalue: boolean
  is_required: boolean
  display_order: number
  dictionary_id?: string | null
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
  master_id: string | null // этап 7 (FR-126)
  master: { id: string; name: string; status: Material['status'] } | null
  children: { id: string; name: string; status: Material['status']; group_id: string }[]
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

// Этап 6: файлы (§6.2–6.4) и версии (§5, FR-144–148)
export interface FileState {
  file_id: string | null
  filename?: string
  mime_type?: string
  size_bytes?: number
  scan_state: 'pending_scan' | 'scanning' | 'ready' | 'infected' | null
  pdf_state: 'none' | 'converting' | 'ready_pdf' | 'convert_failed' | null
}

export interface VersionInfo {
  number: number
  author_id: string
  created_at: string
}

export interface VersionDiff {
  number: number
  file_changed: boolean
  text_diff: string[]
  metadata_changes: { field: string; old: string; new: string }[]
}

// Этап 7: комментарии (7.6, FR-096–098)
export interface CommentInfo {
  id: string
  material_id: string
  author_id: string
  text: string
  created_at: string
}
