// Разделы «Мои материалы», «На проверке», «Архив» (US-006, FR-123–125).
import { useEffect, useState } from 'react'
import { api } from './auth'
import { STATUS_RU, fmtDate, type Material, type Page } from './types'

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
  const PER_PAGE = 50

  useEffect(() => {
    api<Page<Material>>(`/materials?section=${section}&page=${page}&per_page=${PER_PAGE}`)
      .then((p) => {
        setItems(p.items)
        setTotal(p.total)
      })
      .catch(() => {
        setItems([])
        setTotal(0)
      })
  }, [section, page, refreshToken])

  return (
    <div>
      <h2>Разделы</h2>
      <p>
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => { setSection(s.key); setPage(1) }}
            style={{
              marginRight: 8,
              fontWeight: section === s.key ? 'bold' : 'normal',
              borderBottom: section === s.key ? '2px solid #333' : 'none',
            }}
          >
            {s.label}
          </button>
        ))}
      </p>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={th}>Название</th>
            <th style={th}>Статус</th>
            <th style={th}>Изменён</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.id} onClick={() => onOpenMaterial(m.id)} style={{ cursor: 'pointer' }}>
              <td style={td}>{m.name}</td>
              <td style={td}>{STATUS_RU[m.status]}</td>
              <td style={td}>{fmtDate(m.updated_at)}</td>
            </tr>
          ))}
          {items.length === 0 && <tr><td style={td} colSpan={3}>Пусто</td></tr>}
        </tbody>
      </table>
      {total > PER_PAGE && (
        <p>
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>←</button>{' '}
          Страница {page}{' '}
          <button disabled={page >= Math.ceil(total / PER_PAGE)} onClick={() => setPage(page + 1)}>→</button>
        </p>
      )}
    </div>
  )
}

const th: React.CSSProperties = { textAlign: 'left', borderBottom: '2px solid #ccc', padding: 6 }
const td: React.CSSProperties = { borderBottom: '1px solid #eee', padding: 6 }
