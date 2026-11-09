// Этап 9: настройка уведомлений (US-047, FR-134/135/140) — только СА.
// Матрица «триггер → типы получателей»; изменение фиксируется в аудите (FR-140).
import { useCallback, useEffect, useState } from 'react'
import { api } from './auth'

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
      <h2>Настройка уведомлений</h2>
      <p style={{ color: '#555' }}>
        Модель «триггер → типы получателей» (US-047). Общий триггер «изменение статуса»
        по умолчанию отключён (FR-134); специализированные триггеры имеют приоритет.
      </p>
      {error && <p style={{ color: '#c00' }}>{error}</p>}
      {savedMsg && <p style={{ color: '#060' }}>{savedMsg}</p>}
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th style={th}>Триггер</th>
            <th style={th}>Получатели</th>
            <th style={th}>Включён</th>
            <th style={th}></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.event_type}>
              <td style={td}>{EVENT_TITLES[t.event_type] ?? t.event_type}</td>
              <td style={td}>
                {t.recipients.length === 0 && <em style={{ color: '#888' }}>нет</em>}
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {t.recipients.map((r, i) => (
                    <li key={i}>{recipientText(r)}</li>
                  ))}
                </ul>
              </td>
              <td style={td}>{t.enabled ? 'да' : 'нет'}</td>
              <td style={td}>
                <button onClick={() => toggleEnabled(t)}>
                  {t.enabled ? 'Отключить' : 'Включить'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

const th: React.CSSProperties = { borderBottom: '2px solid #333', textAlign: 'left', padding: '6px 8px' }
const td: React.CSSProperties = { borderBottom: '1px solid #ddd', padding: '6px 8px', verticalAlign: 'top' }
