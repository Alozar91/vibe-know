// Этап 9: лента уведомлений (US-039, FR-136–138) + колокольчик в шапке.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './auth'

// Русские подписи типов событий (11.1)
const EVENT_TITLES: Record<string, string> = {
  material_sent_to_review: 'Материал отправлен на проверку',
  material_rejected: 'Материал отклонён',
  material_archived: 'Материал заархивирован',
  child_auto_archived: 'Подчинённый материал архивирован автоматически',
  master_changed: 'Мастер-материал изменён',
  material_changed_on_review: 'Материал изменён на проверке',
  status_changed: 'Изменение статуса материала',
  file_blocked: 'Файл заблокирован антивирусом',
}

interface NotificationItem {
  id: string
  event_type: string
  material_id: string | null
  read_at: string | null
  created_at: string | null
}

export function useUnreadCount(pollMs = 20000): number {
  // Счётчик непрочитанных (FR-137); опрос — NFR-007 (доставка in-app ≤ 30 с
  // обеспечивает диспетчер ≤ 15 с + интервал опроса UI)
  const [unread, setUnread] = useState(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const tick = useCallback(async () => {
    try {
      const r = await api<{ unread: number }>('/notifications:unread-count')
      setUnread(r.unread)
    } catch {
      /* молча: шапка не должна падать */
    }
  }, [])
  useEffect(() => {
    let cancelled = false
    const loop = async () => {
      await tick()
      if (!cancelled) timer.current = setTimeout(loop, pollMs)
    }
    loop()
    return () => {
      cancelled = true
      if (timer.current) clearTimeout(timer.current)
    }
  }, [tick, pollMs])
  return unread
}

const fmtDate = (s: string | null) =>
  s ? new Date(s).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : ''

export default function NotificationBell({ unread }: { unread: number }) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<NotificationItem[]>([])
  const [total, setTotal] = useState(0)

  const load = useCallback(async (unreadOnly = false) => {
    const r = await api<{ items: NotificationItem[]; total: number }>(
      `/notifications?per_page=50${unreadOnly ? '&unread_only=true' : ''}`,
    )
    setItems(r.items)
    setTotal(r.total)
  }, [])

  const toggle = useCallback(() => {
    setOpen((o) => {
      if (!o) load().catch(console.error)
      return !o
    })
  }, [load])

  const markRead = async (id: string) => {
    await api(`/notifications/${id}:read`, { method: 'POST' })
    await load()
  }

  const markAll = async () => {
    await api('/notifications:read-all', { method: 'POST' })
    await load()
  }

  const openMaterial = (id: string | null) => {
    if (!id) return
    setOpen(false)
    window.dispatchEvent(new CustomEvent('kb:open-material', { detail: id }))
  }

  return (
    <span className="bellwrap">
      <button className="iconbtn" onClick={toggle} title="Уведомления">
        🔔
        {unread > 0 && <span className="dot">{unread}</span>}
      </button>
      {open && (
        <div className="popover">
          <div className="poprow">
            <strong>Уведомления{total ? ` (${total})` : ''}</strong>
            <span className="spacer" />
            <button className="btn small" onClick={markAll} disabled={!items.some((x) => !x.read_at)}>
              Отметить все
            </button>
            <button className="btn small ghost" onClick={() => setOpen(false)} title="Закрыть">✕</button>
          </div>
          {items.length === 0 && <div className="empty">Пока нет уведомлений</div>}
          <ul className="poplist">
            {items.map((n) => (
              <li key={n.id} className={n.read_at ? '' : 'unread'}>
                <div>
                  {EVENT_TITLES[n.event_type] ?? n.event_type}
                  {n.material_id && (
                    <>
                      {' — '}
                      <a href="#" onClick={(e) => { e.preventDefault(); openMaterial(n.material_id) }}>
                        открыть материал
                      </a>
                    </>
                  )}
                </div>
                <div className="poprow" style={{ justifyContent: 'flex-start', marginBottom: 0 }}>
                  <small className="note">{fmtDate(n.created_at)}</small>
                  {!n.read_at && (
                    <button className="btn small" onClick={() => markRead(n.id)}>Прочитано</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </span>
  )
}
