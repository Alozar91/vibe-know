// Этап 10: служебный раздел СА — US-050 (удалённые материалы/группы,
// FR-021/FR-090: только просмотр, восстановление запрещено) + service-tasks
// (FR-012, US-004 ш.5: закрытие только после передачи права) + /tasks (NFR-014).
import { useCallback, useEffect, useState } from 'react'
import { api } from './auth'

interface DeletedMaterial {
  id: string
  name: string
  group_id: string
  status: string
  deleted_at: string | null
}

interface DeletedGroup {
  id: string
  name: string
  path: string
  deleted_at: string | null
}

interface ServiceTask {
  id: string
  task_type: string
  payload: Record<string, unknown>
  state: string
  created_at: string | null
  closed_at: string | null
}

interface TasksSummary {
  summary: Record<string, Record<string, number>>
  items: Array<{
    id: string
    task_type: string
    object_type: string | null
    object_id: string | null
    state: string
    attempts: number
    last_error: string | null
    scheduled_at: string | null
    finished_at: string | null
  }>
}

const fmt = (s: string | null) =>
  s ? new Date(s).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'medium' }) : '—'

export default function ServiceDesk() {
  const [mats, setMats] = useState<DeletedMaterial[]>([])
  const [groups, setGroups] = useState<DeletedGroup[]>([])
  const [tasks, setTasks] = useState<ServiceTask[]>([])
  const [showClosed, setShowClosed] = useState(false)
  const [sysTasks, setSysTasks] = useState<TasksSummary | null>(null)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(async (withClosed = showClosed) => {
    try {
      // /materials/deleted — envelope {items,total}; /groups/deleted — плоский список
      const [m, g, st, sys] = await Promise.all([
        api<{ items: DeletedMaterial[]; total: number }>('/materials/deleted'),
        api<DeletedGroup[]>('/groups/deleted'),
        api<ServiceTask[]>(`/service-tasks${withClosed ? '?all=true' : ''}`),
        api<TasksSummary>('/tasks'),
      ])
      setMats(m.items ?? [])
      setGroups(Array.isArray(g) ? g : [])
      setTasks(st)
      setSysTasks(sys)
      setError('')
    } catch (e) {
      setError(String((e as Error).message))
    }
  }, [showClosed])

  useEffect(() => { load() }, [load])

  const closeTask = async (t: ServiceTask) => {
    try {
      await api(`/service-tasks/${t.id}:close`, { method: 'POST' })
      setMsg('Задача закрыта (условие FR-012 выполнено)')
      await load()
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  return (
    <section>
      <h2>Служебный раздел</h2>
      {error && <p style={{ color: '#c00' }}>{error}</p>}
      {msg && <p style={{ color: '#060' }}>{msg}</p>}

      <h3>Удалённые материалы (US-050)</h3>
      <p style={{ color: '#555', margin: '4px 0 8px' }}>
        Только просмотр — восстановление не предусмотрено (FR-021, FR-090).
      </p>
      {mats.length === 0 && <p>Нет удалённых материалов.</p>}
      {mats.length > 0 && (
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13, marginBottom: 16 }}>
          <thead>
            <tr><th style={th}>Название</th><th style={th}>Статус</th><th style={th}>Удалён</th></tr>
          </thead>
          <tbody>
            {mats.map((m) => (
              <tr key={m.id}>
                <td style={td}>{m.name}</td>
                <td style={td}>{m.status}</td>
                <td style={td}>{fmt(m.deleted_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Удалённые группы</h3>
      {groups.length === 0 && <p>Нет удалённых групп.</p>}
      {groups.length > 0 && (
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13, marginBottom: 16 }}>
          <thead>
            <tr><th style={th}>Название</th><th style={th}>Путь</th><th style={th}>Удалена</th></tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.id}>
                <td style={td}>{g.name}</td>
                <td style={td}><code>{g.path}</code></td>
                <td style={td}>{fmt(g.deleted_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Задачи передачи права ревью (FR-012)</h3>
      <p style={{ color: '#555', margin: '4px 0 8px' }}>
        Закрытие возможно, только когда право «Ревью (утверждение)» уже назначено
        другому активному пользователю (US-004 ш.5, US-044).
      </p>
      <label style={{ fontSize: 13 }}>
        <input type="checkbox" checked={showClosed}
               onChange={(e) => { setShowClosed(e.target.checked); load(e.target.checked) }} />{' '}
        показывать закрытые
      </label>
      {tasks.length === 0 && <p>Нет задач.</p>}
      {tasks.length > 0 && (
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13, marginBottom: 16 }}>
          <thead>
            <tr><th style={th}>Тип</th><th style={th}>Данные</th><th style={th}>Состояние</th><th style={th}>Создана</th><th style={th}></th></tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id}>
                <td style={td}><code>{t.task_type}</code></td>
                <td style={{ ...td, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {JSON.stringify(t.payload)}
                </td>
                <td style={td}>{t.closed_at ? 'закрыта' : (t.state || 'открыта')}</td>
                <td style={td}>{fmt(t.created_at)}</td>
                <td style={td}>
                  {!t.closed_at && <button onClick={() => closeTask(t)}>Закрыть</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Состояние фоновых задач (NFR-014)</h3>
      {sysTasks && (
        <>
          <table style={{ borderCollapse: 'collapse', fontSize: 13, marginBottom: 8 }}>
            <thead>
              <tr><th style={th}>Тип задачи</th><th style={th}>Счётчики по состояниям</th></tr>
            </thead>
            <tbody>
              {Object.entries(sysTasks.summary).map(([type, states]) => (
                <tr key={type}>
                  <td style={td}><code>{type}</code></td>
                  <td style={td}>{Object.entries(states).map(([s, c]) => `${s}=${c}`).join(', ')}</td>
                </tr>
              ))}
              {Object.keys(sysTasks.summary).length === 0 && (
                <tr><td style={td} colSpan={2}>Задач нет.</td></tr>
              )}
            </tbody>
          </table>
          <details>
            <summary style={{ cursor: 'pointer', fontSize: 13 }}>
              Последние задачи ({sysTasks.items.length})
            </summary>
            <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
              <thead>
                <tr><th style={th}>Тип</th><th style={th}>Объект</th><th style={th}>Состояние</th><th style={th}>Попытки</th><th style={th}>Ошибка</th><th style={th}>Завершена</th></tr>
              </thead>
              <tbody>
                {sysTasks.items.map((t) => (
                  <tr key={t.id}>
                    <td style={td}><code>{t.task_type}</code></td>
                    <td style={td}>{t.object_type ?? '—'}</td>
                    <td style={td}>{t.state}</td>
                    <td style={td}>{t.attempts}</td>
                    <td style={{ ...td, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{t.last_error ?? ''}</td>
                    <td style={td}>{fmt(t.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  )
}

const th: React.CSSProperties = { borderBottom: '2px solid #333', textAlign: 'left', padding: '4px 8px' }
const td: React.CSSProperties = { borderBottom: '1px solid #ddd', padding: '4px 8px', verticalAlign: 'top' }
