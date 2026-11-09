// Этап 10: журнал аудита (US-049, FR-140–143) — только СА.
// Таблица с фильтрами (action/object_type/даты) + выгрузка NDJSON (FR-143).
import { useCallback, useEffect, useState } from 'react'
import { api, getAccessToken } from './auth'

interface AuditRow {
  id: number
  occurred_at: string | null
  actor_user_id: string | null
  actor_display_name: string | null
  actor_is_service: boolean
  action: string
  object_type: string
  object_id: string | null
  details: Record<string, unknown>
}

const fmt = (s: string | null) =>
  s ? new Date(s).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'medium' }) : ''

export default function AuditLog() {
  const [rows, setRows] = useState<AuditRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [objectType, setObjectType] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async (p = page, a = action, ot = objectType) => {
    try {
      const qs = new URLSearchParams({ page: String(p), per_page: '50' })
      if (a) qs.set('action', a)
      if (ot) qs.set('object_type', ot)
      const r = await api<{ items: AuditRow[]; total: number }>(`/audit?${qs}`)
      setRows(r.items)
      setTotal(r.total)
      setError('')
    } catch (e) {
      setError(String((e as Error).message))
    }
  }, [page, action, objectType])

  useEffect(() => { load(1) }, [])

  const exportNdjson = () => {
    // FR-143: выгрузка NDJSON (GET /audit/export) — fetch+blob с Bearer,
    // затем скачивание файла (Authorization в query не передаём)
    const qs = new URLSearchParams()
    if (action) qs.set('action', action)
    if (objectType) qs.set('object_type', objectType)
    const t = getAccessToken()
    if (!t) return
    fetch(`/api/v1/audit/export?${qs}`, { headers: { Authorization: `Bearer ${t}` } })
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.blob() })
      .then((b) => {
        const url = URL.createObjectURL(b)
        const a = document.createElement('a')
        a.href = url
        a.download = 'audit-export.ndjson'
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((e) => setError(String(e.message)))
  }

  return (
    <section>
      <h2>Журнал аудита</h2>
      <p style={{ color: '#555' }}>
        Записи неизменяемы (FR-141); просмотры материалов не фиксируются (FR-142).
      </p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <input placeholder="action (напр. material.update)" value={action}
               onChange={(e) => setAction(e.target.value)} />
        <input placeholder="object_type" value={objectType}
               onChange={(e) => setObjectType(e.target.value)} />
        <button onClick={() => { setPage(1); load(1) }}>Фильтр</button>
        <button onClick={exportNdjson}>Выгрузить NDJSON (FR-143)</button>
      </div>
      {error && <p style={{ color: '#c00' }}>{error}</p>}
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={th}>Когда</th><th style={th}>Кто</th><th style={th}>Действие</th>
            <th style={th}>Объект</th><th style={th}>Детали</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={td}>{fmt(r.occurred_at)}</td>
              <td style={td}>
                {r.actor_is_service
                  ? 'система'
                  : (r.actor_display_name || (r.actor_user_id ? r.actor_user_id.slice(0, 8) + '…' : '—'))}
              </td>
              <td style={td}>{r.action}</td>
              <td style={td}>{r.object_type}{r.object_id ? ` (${r.object_id.slice(0, 8)}…)` : ''}</td>
              <td style={{ ...td, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {JSON.stringify(r.details)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 8 }}>
        Страница {page}, всего {total}
        <button style={{ marginLeft: 8 }} disabled={page <= 1}
                onClick={() => { setPage(page - 1); load(page - 1) }}>← Назад</button>
        <button style={{ marginLeft: 4 }} disabled={(page * 50) >= total}
                onClick={() => { setPage(page + 1); load(page + 1) }}>Вперёд →</button>
      </div>
    </section>
  )
}

const th: React.CSSProperties = { borderBottom: '2px solid #333', textAlign: 'left', padding: '4px 8px' }
const td: React.CSSProperties = { borderBottom: '1px solid #ddd', padding: '4px 8px', verticalAlign: 'top' }
