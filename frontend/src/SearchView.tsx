// Глобальный поиск (US-034–036): шапка → выдача (материалы + блок групп),
// фильтры (FR-115/116), сортировка (FR-117), подсветка (FR-118), пагинация.
// Открытие материала из выдачи → POST /search-opens (§7.6, fire-and-forget).
import { useCallback, useEffect, useState } from 'react'
import { api } from './auth'
import { STATUS_RU, fmtDate, type Material, type Page } from './types'

interface GroupHit { id: string; name: string; path: string }
interface SearchPage extends Page<Material> {
  groups: GroupHit[]
  query: string
  search_event_id: string | null
}

// headline приходит из ts_headline (PG) — только на живом стеке
declare module './types' {
  interface Material {
    headline?: string
  }
}

interface Props {
  onOpenMaterial: (id: string) => void
  initialQuery: string
}

export default function SearchView({ onOpenMaterial, initialQuery }: Props) {
  const [q, setQ] = useState(initialQuery)
  const [partial, setPartial] = useState(false)
  const [includeArchive, setIncludeArchive] = useState(false)
  const [masterFilter, setMasterFilter] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState('relevance')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [data, setData] = useState<SearchPage | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const PER_PAGE = 50 // FR-121

  const run = useCallback(() => {
    setBusy(true)
    setError('')
    const p = new URLSearchParams()
    if (q.trim()) p.set('q', q.trim())
    p.set('partial', String(partial))
    p.set('include_archive', String(includeArchive))
    if (masterFilter) p.set('master_filter', masterFilter)
    if (status) p.set('status', status)
    p.set('sort', sort)
    p.set('order', order)
    p.set('page', String(page))
    p.set('per_page', String(PER_PAGE))
    api<SearchPage>(`/search?${p.toString()}`)
      .then(setData)
      .catch((e) => setError(e.detail ?? String(e)))
      .finally(() => setBusy(false))
  }, [q, partial, includeArchive, masterFilter, status, sort, order, page])

  useEffect(() => {
    run()
  }, [run])

  // §7.6: открытие из выдачи → событие открытия (fire-and-forget)
  const openMaterial = (id: string) => {
    if (data?.search_event_id) {
      api('/search-opens', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ search_event_id: data.search_event_id, material_id: id }),
      }).catch(() => undefined) // ошибки приёма не влияют на переход
    }
    onOpenMaterial(id)
  }

  // FR-118: подсветка совпадений в названии на клиенте
  const highlight = (name: string) => {
    const term = q.trim()
    if (!term) return name
    const idx = name.toLowerCase().indexOf(term.toLowerCase())
    if (idx < 0) return name
    return (
      <>
        {name.slice(0, idx)}
        <mark>{name.slice(idx, idx + term.length)}</mark>
        {name.slice(idx + term.length)}
      </>
    )
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / PER_PAGE)) : 1
  const canPrev = page > 1
  const canNext = data ? page * PER_PAGE < data.total : false

  return (
    <div>
      <h2>Поиск</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Поисковый запрос (фраза — в кавычках, FR-113)"
               style={{ width: 420 }}
               onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); run() } }} />
        <button onClick={() => { setPage(1); run() }} disabled={busy}>Найти</button>
        <label>
          <input type="checkbox" checked={partial}
                 onChange={(e) => { setPartial(e.target.checked); setPage(1) }} />
          {' '}Частичное совпадение (FR-114)
        </label>
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <label>Статус:
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
            <option value="">любой</option>
            {Object.entries(STATUS_RU).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
          </select>
        </label>
        <label>Архив:
          <input type="checkbox" checked={includeArchive}
                 onChange={(e) => { setIncludeArchive(e.target.checked); setPage(1) }} />
        </label>
        <label>Связи:
          <select value={masterFilter} onChange={(e) => { setMasterFilter(e.target.value); setPage(1) }}>
            <option value="">все</option>
            <option value="masters">только мастер-материалы</option>
            <option value="children">только подчинённые</option>
          </select>
        </label>
        <label>Сортировка:
          <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1) }}>
            <option value="relevance">релевантность</option>
            <option value="name">название</option>
            <option value="updated_at">дата изменения</option>
            <option value="published_at">дата публикации</option>
          </select>
        </label>
        <button onClick={() => setOrder(order === 'asc' ? 'desc' : 'asc')}>
          {order === 'asc' ? '↑' : '↓'}
        </button>
      </div>

      {error && <p style={{ color: '#b00' }}>{error}</p>}

      {data && (
        <>
          <p style={{ color: '#555' }}>
            Найдено: {data.total}
            {data.query && <> · запрос: «{data.query}»</>}
          </p>

          {data.groups.length > 0 && (
            <div style={{ border: '1px solid #ccc', borderRadius: 6, padding: '8px 12px', marginBottom: 12 }}>
              <strong>Группы</strong>
              <ul style={{ margin: '6px 0 0' }}>
                {data.groups.map((g) => (
                  <li key={g.id}>{g.name} <small style={{ color: '#777' }}>{g.path}</small></li>
                ))}
              </ul>
            </div>
          )}

          <ul style={{ listStyle: 'none', padding: 0 }}>
            {data.items.map((m) => (
              <li key={m.id} style={{ padding: '8px 0', borderBottom: '1px solid #eee' }}>
                <a href="#" onClick={(e) => { e.preventDefault(); openMaterial(m.id) }}
                   style={{ fontWeight: 'bold' }}>
                  {highlight(m.name)}
                </a>{' '}
                <small>
                  <span style={badgeStyle}>{STATUS_RU[m.status] ?? m.status}</span>
                  {' · '}{fmtDate(m.updated_at)}
                </small>
                {m.headline && (
                  <div style={{ fontSize: 12, color: '#555' }}
                       dangerouslySetInnerHTML={{ __html: m.headline }} />
                )}
              </li>
            ))}
          </ul>
          {data.items.length === 0 && <p style={{ color: '#777' }}>Ничего не найдено</p>}

          <div style={{ marginTop: 12 }}>
            <button disabled={!canPrev} onClick={() => setPage(page - 1)}>← Назад</button>{' '}
            <span>Стр. {page} из {pages}</span>{' '}
            <button disabled={!canNext} onClick={() => setPage(page + 1)}>Вперёд →</button>
          </div>
        </>
      )}
    </div>
  )
}

const badgeStyle: React.CSSProperties = { padding: '1px 6px', borderRadius: 4, background: '#eee' }
