// Глобальный поиск (US-034–036): шапка → выдача (материалы + блок групп),
// фильтры (FR-115/116), сортировка (FR-117), подсветка (FR-118), пагинация.
// Открытие материала из выдачи → POST /search-opens (§7.6, fire-and-forget).
// Реорганизация frontend: запрос — через src/api/search.
import { useState } from 'react'
import { postSearchOpen, search } from '../../../api/search'
import { errText, fmtDate, STATUS_RU } from '../../../shared/lib/dicts'
import { Empty, Err, Pager, StatusBadge } from '../../../shared/ui/index'
import type { SearchPage } from '../../../api/search'

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
  const [searchType, setSearchType] = useState<'fulltext' | 'vector' | 'hybrid'>('fulltext')
  const [sort, setSort] = useState('relevance')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [data, setData] = useState<SearchPage | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const PER_PAGE = 50 // FR-121

  async function run() {
    setBusy(true)
    setError('')
    try {
      setData(await search({
        q, partial, includeArchive, masterFilter, status, searchType, sort, order, page, perPage: PER_PAGE,
      }))
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  // §7.6: открытие из выдачи → событие открытия (fire-and-forget)
  const openMaterial = (id: string) => {
    if (data?.search_event_id) {
      postSearchOpen(data.search_event_id, id).catch(() => undefined) // ошибки приёма не влияют на переход
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
  // Гибрид: полоса — доля от лучшего скора этой выдачи (шкала RRF относительна)
  const maxScore = data && searchType === 'hybrid'
    ? Math.max(...data.items.map((m) => m.score ?? 0), Number.EPSILON)
    : 1

  return (
    <div>
      <div className="pagehead"><h2>Поиск</h2></div>
      <div className="panel">
        <div className="toolbar">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поисковый запрос (фраза — в кавычках, FR-113)"
            style={{ width: 420, maxWidth: '100%' }}
            onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); void run() } }}
          />
          <button className="btn primary" onClick={() => { setPage(1); void run() }} disabled={busy}>Найти</button>
          <label className="srchfld">Режим:
            <select value={searchType} onChange={(e) => { setSearchType(e.target.value as 'fulltext' | 'vector' | 'hybrid'); setPage(1) }}>
              <option value="fulltext">полнотекстовый</option>
              <option value="vector">векторный (RAG)</option>
              <option value="hybrid">гибридный (RRF)</option>
            </select>
          </label>
          <label className="checkrow">
            <input type="checkbox" checked={partial}
                   onChange={(e) => { setPartial(e.target.checked); setPage(1) }} />
            Частичное совпадение (FR-114)
          </label>
          <span className="spacer" />
          {busy && <span className="meta">Поиск…</span>}
        </div>
        <div className="toolbar">
          <label className="srchfld">Статус:
            <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
              <option value="">любой</option>
              {Object.entries(STATUS_RU).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
            </select>
          </label>
          <label className="srchfld">Архив:
            <input type="checkbox" checked={includeArchive}
                   onChange={(e) => { setIncludeArchive(e.target.checked); setPage(1) }} />
          </label>
          <label className="srchfld">Связи:
            <select value={masterFilter} onChange={(e) => { setMasterFilter(e.target.value); setPage(1) }}>
              <option value="">все</option>
              <option value="masters">только мастер-материалы</option>
              <option value="children">только подчинённые</option>
            </select>
          </label>
          {searchType === 'fulltext' && (
            <>
              <label className="srchfld">Сортировка:
                <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1) }}>
                  <option value="relevance">релевантность</option>
                  <option value="name">название</option>
                  <option value="updated_at">дата изменения</option>
                  <option value="published_at">дата публикации</option>
                </select>
              </label>
              <button className="pg" onClick={() => setOrder(order === 'asc' ? 'desc' : 'asc')}>
                {order === 'asc' ? '↑' : '↓'}
              </button>
            </>
          )}
        </div>
      </div>

      <Err>{error}</Err>

      {data && (
        <>
          <p className="note">
            Найдено: <b>{data.total}</b>
            {data.query && <> · запрос: «{data.query}»</>}
          </p>

          {data.groups.length > 0 && (
            <div className="panel" style={{ marginBottom: 14 }}>
              <div className="toolbar"><strong style={{ fontSize: 13 }}>Группы</strong></div>
              <ul className="grouphits">
                {data.groups.map((g) => (
                  <li key={g.id}>{g.name} <small className="mono">{g.path}</small></li>
                ))}
              </ul>
            </div>
          )}

          <div className="panel">
            <ul className="hits">
              {data.items.map((m) => (
                <li key={m.id} className="searchhit">
                  <a href="#" onClick={(e) => { e.preventDefault(); openMaterial(m.id) }}>
                    {highlight(m.name)}
                  </a>{' '}
                  <StatusBadge status={m.status} />{' '}
                  <small className="mono">{fmtDate(m.updated_at)}</small>
                  {typeof m.score === 'number' && searchType !== 'fulltext' && (
                    <ScoreBar score={m.score} mode={searchType} max={maxScore} />
                  )}
                  {m.headline && (
                    <div className="hltext" dangerouslySetInnerHTML={{ __html: m.headline }} />
                  )}
                </li>
              ))}
            </ul>
            {data.items.length === 0 && <Empty>Ничего не найдено</Empty>}

            {pages > 1 && (
              <Pager
                page={page}
                pages={pages}
                onPrev={() => canPrev && setPage(page - 1)}
                onNext={() => canNext && setPage(page + 1)}
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}

/** Релевантность в выдаче (§7.7): полоса + число.
 *
 * vector — score = 1−dist, косинусная близость запроса и лучшего чанка
 * материала (0..1; 1 = совпадение) — полоса в абсолютной шкале.
 * hybrid — RRF-скор Σ1/(60+rank): максимум мал (2/(60+1) ≈ 0.033) и шкала
 * относительна — полоса показывает долю от лучшего результата этой выдачи
 * (лидер всегда 100% — эталон сравнения), число — абсолютное значение.
 */
export function ScoreBar({ score, mode, max }: { score: number; mode: 'vector' | 'hybrid'; max: number }) {
  const title = mode === 'vector'
    ? 'Векторная близость запроса и лучшего фрагмента материала (1 — совпадение)'
    : 'Гибридный ранг (RRF): сумма вкладов полнотекстового и векторного потоков; полоса — доля от лучшего результата выдачи'
  const frac = mode === 'vector' ? score : score / max
  return (
    <span className="scorebar" title={title}>
      <span className="sb-track">
        <span
          className={frac >= 0.75 ? 'sb-fill hi' : frac >= 0.45 ? 'sb-fill mid' : 'sb-fill low'}
          style={{ width: `${Math.max(2, Math.min(100, frac * 100))}%` }}
        />
      </span>
      <span className="sb-num">{mode === 'vector' ? score.toFixed(2) : score.toFixed(4)}</span>
    </span>
  )
}
