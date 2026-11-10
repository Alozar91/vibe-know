// Этап 9: настройка уведомлений (US-047, FR-134/135/140) — только СА.
// Матрица «триггер → типы получателей»; изменение фиксируется в аудите (FR-140).
import { useCallback, useEffect, useState } from 'react'
import { api } from './auth'
import { Err, Ok } from './ui'

const EVENT_TITLES: Record<string, string> = {
  material_sent_to_review: 'Материал отправлен на проверку',
  material_rejected: 'Материал отклонён',
  material_archived: 'Материал заархивирован',
  child_auto_archived: 'Подчинённый материал архивирован автоматически',
  master_changed: 'Мастер-материал изменён',
  material_changed_on_review: 'Материал изменён на проверке',
  status_changed: 'Изменение статуса материала (общий)',
}

const RECIPIENT_LABELS: Record<string, string> = {
  role: 'Роль-шаблон',
  fact_author: 'Автор',
  fact_signatory: 'Подписант',
  fact_last_editor: 'Последний редактор',
  permission_holder: 'Носители права',
}

interface RecipientCfg {
  type: string
  role_id?: string
  permission?: string
  scope?: string
}

interface Trigger {
  event_type: string
  enabled: boolean
  recipients: RecipientCfg[]
}

const recipientText = (r: RecipientCfg) => {
  let t = RECIPIENT_LABELS[r.type] ?? r.type
  if (r.permission) t += ` (${r.permission})`
  if (r.scope === 'children') t += ' [подчинённые]'
  return t
}

export default function NotificationTriggers() {
  const [rows, setRows] = useState<Trigger[]>([])
  const [error, setError] = useState('')
  const [savedMsg, setSavedMsg] = useState('')

  const load = useCallback(async () => {
    try {
      setRows(await api<Trigger[]>('/notification-triggers'))
      setError('')
    } catch (e) {
      setError(String((e as Error).message))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const toggleEnabled = async (t: Trigger) => {
    try {
      await api(`/notification-triggers/${t.event_type}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: !t.enabled, recipients: t.recipients }),
      })
      setSavedMsg(`Триггер «${EVENT_TITLES[t.event_type] ?? t.event_type}» ${!t.enabled ? 'включён' : 'отключён'} (записано в аудит, FR-140)`)
      await load()
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  return (
    <section>
      <div className="pagehead"><h2>Настройка уведомлений</h2></div>
      <p className="note">
        Модель «триггер → типы получателей» (US-047). Общий триггер «изменение статуса»
        по умолчанию отключён (FR-134); специализированные триггеры имеют приоритет.
      </p>
      <Err>{error}</Err>
      <Ok>{savedMsg}</Ok>
      <div className="panel">
        <table className="tbl">
          <thead>
            <tr>
              <th>Триггер</th>
              <th>Получатели</th>
              <th>Включён</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.event_type}>
                <td className="mname">{EVENT_TITLES[t.event_type] ?? t.event_type}</td>
                <td>
                  {t.recipients.length === 0 && <em className="note">нет</em>}
                  <ul className="plainlist">
                    {t.recipients.map((r, i) => (
                      <li key={i}>{recipientText(r)}</li>
                    ))}
                  </ul>
                </td>
                <td>
                  <span className={`chip ${t.enabled ? 'on' : ''}`}>{t.enabled ? 'да' : 'нет'}</span>
                </td>
                <td>
                  <button className="btn small" onClick={() => toggleEnabled(t)}>
                    {t.enabled ? 'Отключить' : 'Включить'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
