// Дерево групп + списки материалов (US-005): группы с view — с содержимым,
// остальные — путь навигации (FR-103); сортировка/пагинация FR-117/121.
import { useCallback, useEffect, useState } from 'react'
import { api } from './auth'
import { STATUS_RU, fmtDate, type GroupNode, type Material, type Page } from './types'

interface Props {
  onOpenMaterial: (id: string) => void
  refreshToken: number // рост → перезагрузка (после мутаций)
}

export default function MaterialsBrowser({ onOpenMaterial, refreshToken }: Props) {
  const [tree, setTree] = useState<GroupNode[]>([])
  const [selected, setSelected] = useState<GroupNode | null>(null)
  const [items, setItems] = useState<Material[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState('updated_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [error, setError] = useState('')
  const PER_PAGE = 50 // FR-121

  useEffect(() => {
    api<GroupNode[]>('/groups')
      .then(setTree)
      .catch((e) => setError(e.detail ?? String(e)))
  }, [refreshToken])

  const loadList = useCallback(() => {
    if (!selected) return
    setError('')
    api<Page<Material>>(`/materials?group_id=${selected.id}&page=${page}&per_page=${PER_PAGE}&sort=${sort}&order=${order}`)
      .then((p) => {
        setItems(p.items)
        setTotal(p.total)
      })
      .catch((e) => {
        setItems([])
        setTotal(0)
        setError(e.detail ?? String(e))
      })
  }, [selected, page, sort, order])

  useEffect(() => {
    loadList()
  }, [loadList, refreshToken])

  const changeSort = (field: string) => {
    if (sort === field) {
      setOrder(order === 'asc' ? 'desc' : 'asc')
    } else {
      setSort(field)
      setOrder('desc')
    }
  }

  const pages = Math.max(1, Math.ceil(total / PER_PAGE))

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
      <aside style={{ minWidth: 260, borderRight: '1px solid #ddd', paddingRight: 16 }}>
        <h3>Группы</h3>
        <GroupTreeView nodes={tree} selected={selected} onSelect={(g) => { setSelected(g); setPage(1) }} />
      </aside>
      <section style={{ flex: 1 }}>
        {error && <p style={{ color: '#b00' }}>{error}</p>}
        {selected ? (
          <>
            <h2>{selected.name} <small style={{ color: '#777' }}>({total})</small></h2>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Название</th>
                  <th style={th} onClick={() => changeSort('status')}>Статус</th>
                  <th style={th} onClick={() => changeSort('updated_at')}>
                    Изменён {sort === 'updated_at' ? (order === 'asc' ? '↑' : '↓') : ''}
                  </th>
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
                {items.length === 0 && !error && (
                  <tr><td style={td} colSpan={3}>Нет материалов</td></tr>
                )}
              </tbody>
            </table>
            {pages > 1 && (
              <p>
                Страница {page} из {pages}{' '}
                <button disabled={page <= 1} onClick={() => setPage(page - 1)}>←</button>{' '}
                <button disabled={page >= pages} onClick={() => setPage(page + 1)}>→</button>
              </p>
            )}
          </>
        ) : (
          <p>Выберите группу в дереве слева (US-005).</p>
        )}
      </section>
    </div>
  )
}

const th: React.CSSProperties = { textAlign: 'left', borderBottom: '2px solid #ccc', padding: 6, cursor: 'pointer' }
const td: React.CSSProperties = { borderBottom: '1px solid #eee', padding: 6 }

function GroupTreeView({ nodes, selected, onSelect, depth = 0 }: {
  nodes: GroupNode[]
  selected: GroupNode | null
  onSelect: (g: GroupNode) => void
  depth?: number
}) {
  return (
    <ul style={{ listStyle: 'none', paddingLeft: depth ? 16 : 0, margin: 0 }}>
      {nodes.map((g) => (
        <li key={g.id}>
          <div
            onClick={() => onSelect(g)}
            style={{
              padding: '3px 6px', cursor: 'pointer', borderRadius: 4,
              background: selected?.id === g.id ? '#dbe7ff' : 'transparent',
            }}
          >
            📁 {g.name}
          </div>
          {g.children && g.children.length > 0 && (
            <GroupTreeView nodes={g.children} selected={selected} onSelect={onSelect} depth={depth + 1} />
          )}
        </li>
      ))}
    </ul>
  )
}
