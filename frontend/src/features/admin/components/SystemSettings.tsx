// Этап 10: параметры системы (US-048, NFR-020) — только СА.
// Реестр system_settings §2.5: просмотр + изменение (аудит — FR-140);
// параметры Keycloak (пароли/сессии) — вне реестра, ссылка на консоль.
// Реорганизация frontend: вызовы — через src/api/admin.
import { useCallback, useEffect, useState } from 'react'
import { getSettings, updateSetting, type Setting } from '../../../api/admin'
import { errText } from '../../../shared/lib/dicts'
import { Err, Ok } from '../../../shared/ui/index'

// Редактируемые простые поля (число/строка); списки/bool — отображаются текстом
export default function SystemSettings() {
  const [rows, setRows] = useState<Setting[]>([])
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      const r = await getSettings()
      setRows(r)
      const d: Record<string, string> = {}
      for (const s of r) d[s.key] = JSON.stringify(s.value)
      setDrafts(d)
      setError('')
    } catch (e) {
      setError(errText(e))
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const save = async (s: Setting) => {
    try {
      // Значение в реестре — jsonb: разбираем введённое как JSON (число, строка, массив)
      let value: unknown
      try {
        value = JSON.parse(drafts[s.key])
      } catch {
        value = drafts[s.key]  // строки без кавычек — как есть
      }
      await updateSetting(s.key, value)
      setMsg(`Параметр «${s.key}» сохранён (записано в аудит, FR-140)`)
      await load()
    } catch (e) {
      setError(errText(e))
    }
  }

  return (
    <section>
      <div className="pagehead"><h2>Параметры системы</h2></div>
      <p className="note">
        Изменение поведения — без правки кода (NFR-020). Политики Keycloak
        (пароли, сессии, блокировка) — в консоли Keycloak (US-048 ш.1).
      </p>
      <Err>{error}</Err>
      <Ok>{msg}</Ok>
      <div className="panel">
        <table className="tbl">
          <thead>
            <tr>
              <th>Ключ</th><th>Значение</th><th>Описание</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.key}>
                <td className="mono">{s.key}</td>
                <td>
                  <input style={{ width: 220 }} value={drafts[s.key] ?? ''}
                         onChange={(e) => setDrafts({ ...drafts, [s.key]: e.target.value })} />
                </td>
                <td className="note">{s.description ?? '—'}</td>
                <td><button className="btn small" onClick={() => void save(s)}>Сохранить</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
