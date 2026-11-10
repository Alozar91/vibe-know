// Разделы «Мои материалы», «На проверке», «Архив» (US-006, FR-123-125).
import { useEffect, useState } from 'react'
import { api } from './auth'
import { fmtDate, type Material, type Page } from './types'
import { Empty, Err, Pager, StatusBadge } from './ui'

interface Props {
  onOpenMaterial: (id: string) => void
  refreshToken: number
}

const SECTIONS = [
  { key: 'my', label: 'Мои материалы' },
  { key: 'review', label: 'На проверке' },
  { key: 'archive', label: 'Архив' },
] as const

export default function Sections({ onOpenMaterial, refreshToken }: Props) {
  const [section, setSection] = useState<string>('my')
  const [items, setItems] = useState<Material[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const PER_PAGE = 50

  useEffect(() => {
    api<Page<Material>>(`/materials?section=${section}&page=${page}&per_page=${PER_PAGE}`)
      .then((p) => { setItems(p.items); setTotal(p.total); setError('') })
      .catch((e) => setError(e.detail ?? String(e)))
  }, [section, page, refreshToken])

  const pages = Math.max(1, Math.ceil(total / PER_PAGE))
  const activeLabel = SECTIONS.find((s) => s.key === section)?.label ?? 'Разделы'

  return (
    <div>
      <div className="pagehead">
        <h2>Разделы</h2>
        {total > 0 && <span className="total-pill">{total}</span>}
      </div>
      <div className="chiprow">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            className={`chip ${section === s.key ? 'on' : ''}`}
            onClick={() => { setSection(s.key); setPage(1) }}
          >
            {s.label}
          </button>
        ))}
      </div>
      <Err>{error}</Err>
      <div className="panel">
        <div className="toolbar"><span className="meta">{activeLabel}</span></div>
        <table className="tbl">
          <thead>
            <tr><th>Название</th><th>Статус</th><th>Изменён</th></tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id} className="rowlink" onClick={() => onOpenMaterial(m.id)}>
                <td className="mname">{m.name}</td>
                <td><StatusBadge status={m.status} /></td>
                <td className="nowrap">{fmtDate(m.updated_at)}</td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={3}><Empty>Пусто</Empty></td></tr>}
          </tbody>
        </table>
        {pages > 1 && <Pager page={page} pages={pages} onPrev={() => setPage(page - 1)} onNext={() => setPage(page + 1)} />}
      </div>
    </div>
  )
}
