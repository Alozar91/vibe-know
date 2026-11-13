// Этап 10: служебный раздел СА — US-050 (удалённые материалы/группы,
// FR-021/FR-090: только просмотр, восстановление запрещено) + service-tasks
// (FR-012, US-004 ш.5: закрытие только после передачи права) + /tasks (NFR-014).
// Реорганизация frontend: вызовы — через src/api (materials/groups/admin).
import { useCallback, useEffect, useState } from 'react'
import {
  closeServiceTask, getServiceTasks, getTasksSummary,
  type ServiceTask, type TasksSummary,
} from '../../../api/admin'
import { listDeletedMaterials } from '../../../api/materials'
import { listDeletedGroups } from '../../../api/groups'
import { fmtDateTime } from '../../../shared/lib/dicts'
import { Empty, Err, Ok } from '../../../shared/ui/index'
import type { GroupNode, Material } from '../../../shared/types'

interface DeletedMaterial extends Material {
  deleted_at: string | null
}

interface DeletedGroup extends GroupNode {
  deleted_at: string | null
}

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
        listDeletedMaterials(),
        listDeletedGroups(),
        getServiceTasks(withClosed),
        getTasksSummary(),
      ])
      setMats(m)
      setGroups(g)
      setTasks(st)
      setSysTasks(sys)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [showClosed])

  useEffect(() => { void load() }, [load])

  const closeTask = async (t: ServiceTask) => {
    try {
      await closeServiceTask(t.id)
      setMsg('Задача закрыта (условие FR-012 выполнено)')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section>
      <div className="pagehead"><h2>Служебный раздел</h2></div>
      <Err>{error}</Err>
      <Ok>{msg}</Ok>

      <div className="panel">
        <div className="toolbar"><strong style={{ fontSize: 13 }}>Удалённые материалы (US-050)</strong></div>
        <div className="panel-body">
          <p className="note" style={{ margin: '0 0 8px' }}>
            Только просмотр — восстановление не предусмотрено (FR-021, FR-090).
          </p>
        </div>
        {mats.length === 0 && <Empty>Нет удалённых материалов.</Empty>}
        {mats.length > 0 && (
          <table className="tbl">
            <thead>
              <tr><th>Название</th><th>Статус</th><th>Удалён</th></tr>
            </thead>
            <tbody>
              {mats.map((m) => (
                <tr key={m.id}>
                  <td className="mname">{m.name}</td>
                  <td className="mono">{m.status}</td>
                  <td className="nowrap">{fmtDateTime(m.deleted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <div className="toolbar"><strong style={{ fontSize: 13 }}>Удалённые группы</strong></div>
        {groups.length === 0 && <Empty>Нет удалённых групп.</Empty>}
        {groups.length > 0 && (
          <table className="tbl">
            <thead>
              <tr><th>Название</th><th>Путь</th><th>Удалена</th></tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.id}>
                  <td className="mname">{g.name}</td>
                  <td className="mono">{g.path}</td>
                  <td className="nowrap">{fmtDateTime(g.deleted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <div className="toolbar"><strong style={{ fontSize: 13 }}>Задачи передачи права ревью (FR-012)</strong></div>
        <div className="panel-body">
          <p className="note" style={{ margin: '0 0 8px' }}>
            Закрытие возможно, только когда право «Ревью (утверждение)» уже назначено
            другому активному пользователю (US-004 ш.5, US-044).
          </p>
          <label className="checkrow">
            <input type="checkbox" checked={showClosed}
                   onChange={(e) => { setShowClosed(e.target.checked); void load(e.target.checked) }} />
            показывать закрытые
          </label>
        </div>
        {tasks.length === 0 && <Empty>Нет задач.</Empty>}
        {tasks.length > 0 && (
          <table className="tbl">
            <thead>
              <tr><th>Тип</th><th>Данные</th><th>Состояние</th><th>Создана</th><th></th></tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id}>
                  <td className="mono">{t.task_type}</td>
                  <td className="wrap-anywhere mono">{JSON.stringify(t.payload)}</td>
                  <td>{t.closed_at ? 'закрыта' : (t.state || 'открыта')}</td>
                  <td className="nowrap">{fmtDateTime(t.created_at)}</td>
                  <td>
                    {!t.closed_at && <button className="btn small" onClick={() => void closeTask(t)}>Закрыть</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <div className="toolbar"><strong style={{ fontSize: 13 }}>Состояние фоновых задач (NFR-014)</strong></div>
        {sysTasks && (
          <>
            <table className="tbl">
              <thead>
                <tr><th>Тип задачи</th><th>Счётчики по состояниям</th></tr>
              </thead>
              <tbody>
                {Object.entries(sysTasks.summary).map(([type, states]) => (
                  <tr key={type}>
                    <td className="mono">{type}</td>
                    <td>{Object.entries(states).map(([s, c]) => `${s}=${c}`).join(', ')}</td>
                  </tr>
                ))}
                {Object.keys(sysTasks.summary).length === 0 && (
                  <tr><td colSpan={2}><Empty>Задач нет.</Empty></td></tr>
                )}
              </tbody>
            </table>
            <details className="summary-box">
              <summary>Последние задачи ({sysTasks.items.length})</summary>
              <table className="tbl">
                <thead>
                  <tr><th>Тип</th><th>Объект</th><th>Состояние</th><th>Попытки</th><th>Ошибка</th><th>Завершена</th></tr>
                </thead>
                <tbody>
                  {sysTasks.items.map((t) => (
                    <tr key={t.id}>
                      <td className="mono">{t.task_type}</td>
                      <td>{t.object_type ?? '—'}</td>
                      <td>{t.state}</td>
                      <td>{t.attempts}</td>
                      <td className="wrap-anywhere mono">{t.last_error ?? ''}</td>
                      <td className="nowrap">{fmtDateTime(t.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </>
        )}
      </div>
    </section>
  )
}
