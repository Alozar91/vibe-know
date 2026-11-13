// Этап 9: лента уведомлений (US-039, FR-136–138) + колокольчик в шапке.
// Реорганизация frontend: API-вызовы — через src/api/notifications; счётчик
// непрочитанных — TanStack Query с refetchInterval (вместо ручного setTimeout).
import { useCallback, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getUnreadCount, listNotifications, markAllNotificationsRead, markNotificationRead } from '../../../api/notifications'
import { EVENT_TITLES, fmtDateTime } from '../../../shared/lib/dicts'

const POLL_MS = 20_000
// Счётчик непрочитанных (FR-137); опрос — NFR-007 (доставка in-app ≤ 30 с
// обеспечивает диспетчер ≤ 15 с + интервал опроса UI)
export function useUnreadCount(): number {
  const q = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => getUnreadCount().catch(() => 0), // молча: шапка не должна падать
    refetchInterval: POLL_MS,
  })
  return q.data ?? 0
}

export default function NotificationBell({ unread }: { unread: number }) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Awaited<ReturnType<typeof listNotifications>>['items']>([])
  const [total, setTotal] = useState(0)
  const queryClient = useQueryClient()

  const load = useCallback(async (unreadOnly = false) => {
    const r = await listNotifications(unreadOnly)
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
    await markNotificationRead(id)
    await load()
    void queryClient.invalidateQueries({ queryKey: ['notifications', 'unread'] })
  }

  const markAll = async () => {
    await markAllNotificationsRead()
    await load()
    void queryClient.invalidateQueries({ queryKey: ['notifications', 'unread'] })
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
                  <small className="note">{fmtDateTime(n.created_at)}</small>
                  {!n.read_at && (
                    <button className="btn small" onClick={() => void markRead(n.id)}>Прочитано</button>
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
