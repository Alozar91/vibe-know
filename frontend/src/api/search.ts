// Поиск и аналитика (US-034–036, FR-127). LLD §12.4.
import { api } from './client'
import type { Material, Page } from '../shared/types'

export interface GroupHit { id: string; name: string; path: string }

export interface SearchHit extends Material {
  headline?: string
  /** Релевантность (vector/hybrid): vector — 1−dist (0..1); hybrid — RRF. */
  score?: number
}

export interface SearchPage extends Page<SearchHit> {
  groups: GroupHit[]
  query: string
  search_event_id: string | null
}

export interface SearchFilters {
  q: string
  partial: boolean
  includeArchive: boolean
  masterFilter: string
  status: string
  searchType: 'fulltext' | 'vector' | 'hybrid'
  sort: string
  order: 'asc' | 'desc'
  page: number
  perPage: number
}

/** GET /search — глобальный поиск (US-034, FR-110–118). */
export function search(f: SearchFilters): Promise<SearchPage> {
  const p = new URLSearchParams()
  if (f.q.trim()) p.set('q', f.q.trim())
  p.set('partial', String(f.partial))
  p.set('search_type', f.searchType)
  p.set('include_archive', String(f.includeArchive))
  if (f.masterFilter) p.set('master_filter', f.masterFilter)
  if (f.status) p.set('status', f.status)
  p.set('sort', f.sort)
  p.set('order', f.order)
  p.set('page', String(f.page))
  p.set('per_page', String(f.perPage))
  return api<SearchPage>(`/search?${p.toString()}`)
}

/** POST /search-opens — событие открытия из выдачи (§7.6, fire-and-forget). */
export function postSearchOpen(searchEventId: string, materialId: string): Promise<void> {
  return api<void>('/search-opens', {
    method: 'POST',
    body: JSON.stringify({ search_event_id: searchEventId, material_id: materialId }),
  })
}

export interface SearchAnalytics {
  top_queries: { query: string; count: number; total_results: number }[]
  zero_result_queries: { query: string; count: number }[]
  ctr: { opens: number; searches: number; ratio: number }
  text_coverage: { with_text: number; total: number; ratio: number }
}

/** GET /analytics/search — аналитика поиска (US-051, FR-127). */
export function getSearchAnalytics(): Promise<SearchAnalytics> {
  return api<SearchAnalytics>('/analytics/search')
}
