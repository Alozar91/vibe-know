// Этап 10: параметры системы (US-048, NFR-020) — только СА.
// Реестр system_settings §2.5: просмотр + изменение (аудит — FR-140);
// параметры Keycloak (пароли/сессии) — вне реестра, ссылка на консоль.
import { useCallback, useEffect, useState } from 'react'
import { api } from './auth'

interface Setting {
  key: string
  value: unknown
  description: string | null
  updated_at: string | null
}

// Редактируемые простые поля (число/строка); списки/bool — отображаются текстом
export default function SystemSettings() {
  const [rows, setRows] = useState<Setting[]>([])
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      const r = await api<Setting[]>('/settings')
      setRows(r)
      const d: Record<string, string> = {}
      for (const s of r) d[s.key] = JSON.stringify(s.value)
      setDrafts(d)
      setError('')
    } catch (e) {
      setError(String((e as Error).message))
    }
  }, [])

  useEffect(() => { load() }, [load])

  const save = async (s: Setting) => {
    try {
      // Значение в реестре — jsonb: разбираем введённое как JSON (число, строка, массив)
      let value: unknown
      try {
        value = JSON.parse(drafts[s.key])
      } catch {
        value = drafts[s.key]  // строки без кавычек — как есть
      }
      await api(`/settings/${s.key}`, { method: 'PUT', body: JSON.stringify({ value }) })
      setMsg(`Параметр «${s.key}» сохранён (записано в аудит, FR-140)`)
      await load()
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  return (
    <section>
      <h2>Параметры системы</h2>
      <p style={{ color: '#555' }}>
        Изменение поведения — без правки кода (NFR-020). Политики Keycloak
        (пароли, сессии, блокировка) — в консоли Keycloak (US-048 ш.1).
      </p>
      {error && <p style={{ color: '#c00' }}>{error}</p>}
      {msg && <p style={{ color: '#060' }}>{msg}</p>}
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={th}>Ключ</th><th style={th}>Значение</th><th style={th}>Описание</th><th style={th}></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.key}>
              <td style={td}><code>{s.key}</code></td>
              <td style={td}>
                <input style={{ width: 220 }} value={drafts[s.key] ?? ''}
                       onChange={(e) => setDrafts({ ...drafts, [s.key]: e.target.value })} />
              </td>
              <td style={td}>{s.description ?? '—'}</td>
              <td style={td}><button onClick={() => save(s)}>Сохранить</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

const th: React.CSSProperties = { borderBottom: '2px solid #333', textAlign: 'left', padding: '4px 8px' }
const td: React.CSSProperties = { borderBottom: '1px solid #ddd', padding: '4px 8px', verticalAlign: 'top' }
