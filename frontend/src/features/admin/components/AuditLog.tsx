// Этап 10: журнал аудита (US-049, FR-140–143) — только СА.
// Таблица с фильтрами (action/object_type/даты) + выгрузка NDJSON (FR-143).
// Реорганизация frontend: вызовы — через src/api/admin.
import { useCallback, useEffect, useState } from 'react'
import { exportAuditNdjson, listAudit } from '../../../api/admin'
import { fmtDateTime } from '../../../shared/lib/dicts'
import { Empty, Err, Pager } from '../../../shared/ui/index'

export default function AuditLog() {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof listAudit>>['items']>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [objectType, setObjectType] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async (p = page, a = action, ot = objectType) => {
    try {
      const r = await listAudit(p, a, ot)
      setRows(r.items)
      setTotal(r.total)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [page, action, objectType])

  useEffect(() => { void load(1) }, [])

  const exportNdjson = () => {
    // FR-143: выгрузка NDJSON (GET /audit/export) — fetch+blob с Bearer,
    // затем скачивание файла (Authorization в query не передаём)
    exportAuditNdjson(action, objectType)
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.blob() })
      .then((b) => {
        const url = URL.createObjectURL(b)
        const a = document.createElement('a')
        a.href = url
        a.download = 'audit-export.ndjson'
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((e) => setError(String(e instanceof Error ? e.message : e)))
  }

  const pages = Math.max(1, Math.ceil(total / 50))

  return (
    <section>
      <div className="pagehead"><h2>Журнал аудита</h2></div>
      <p className="note">
        Записи неизменяемы (FR-141); просмотры материалов не фиксируются (FR-142).
      </p>
      <div className="panel">
        <div className="toolbar">
          <input placeholder="action (напр. material.update)" value={action}
                 onChange={(e) => setAction(e.target.value)} />
          <input placeholder="object_type" value={objectType}
                 onChange={(e) => setObjectType(e.target.value)} />
          <button className="btn" onClick={() => { setPage(1); void load(1) }}>Фильтр</button>
          <span className="spacer" />
          <button className="btn ghost" onClick={exportNdjson}>Выгрузить NDJSON</button>
        </div>
        <Err>{error}</Err>
        <table className="tbl">
          <thead>
            <tr>
              <th>Когда</th><th>Кто</th><th>Действие</th>
              <th>Объект</th><th>Детали</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{fmtDateTime(r.occurred_at)}</td>
                <td>
                  {r.actor_is_service
                    ? 'система'
                    : (r.actor_display_name || (r.actor_user_id ? r.actor_user_id.slice(0, 8) + '…' : '—'))}
                </td>
                <td className="mono">{r.action}</td>
                <td className="mono">{r.object_type}{r.object_id ? ` (${r.object_id.slice(0, 8)}…)` : ''}</td>
                <td className="wrap-anywhere mono">{JSON.stringify(r.details)}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5}><Empty>Записей нет</Empty></td></tr>}
          </tbody>
        </table>
        <Pager page={page} pages={pages} total={total} onPrev={() => { setPage(page - 1); void load(page - 1) }} onNext={() => { setPage(page + 1); void load(page + 1) }} />
      </div>
    </section>
  )
}
