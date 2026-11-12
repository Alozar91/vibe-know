// Уведомления: лента, счётчик непрочитанных (US-039, FR-136–138). Этап 9.
import { api } from './client'

export interface NotificationItem {
  id: string
  event_type: string
  material_id: string | null
  read_at: string | null
  created_at: string | null
}

/** GET /notifications — лента (FR-136). */
export function listNotifications(unreadOnly = false):
  Promise<{ items: NotificationItem[]; total: number }> {
  return api<{ items: NotificationItem[]; total: number }>(
    `/notifications?per_page=50${unreadOnly ? '&unread_only=true' : ''}`,
  )
}

/** GET /notifications:unread-count — счётчик для колокольчика (FR-137). */
export function getUnreadCount(): Promise<number> {
  return api<{ unread: number }>('/notifications:unread-count').then((r) => r.unread)
}

/** POST /notifications/{id}:read — отметить прочитанным. */
export function markNotificationRead(id: string): Promise<void> {
  return api<void>(`/notifications/${id}:read`, { method: 'POST' })
}

/** POST /notifications:read-all — отметить все. */
export function markAllNotificationsRead(): Promise<void> {
  return api<void>('/notifications:read-all', { method: 'POST' })
}
