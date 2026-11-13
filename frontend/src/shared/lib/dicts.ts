// Русские подписи статусов/состояний + утилиты форматирования.
// Реорганизация frontend: единое место (раньше STATUS_RU дублировался
// в types.ts и ui.tsx, fmtDate — в types.ts, ещё копии fmt — в экранах).
import type { FileState, Material } from '../types'

export const STATUS_RU: Record<Material['status'], string> = {
  draft: 'Черновик',
  in_review: 'На проверке',
  approved: 'Утверждён',
  published: 'Публикация',
  archived: 'Архив',
}

export const SCAN_RU: Record<NonNullable<FileState['scan_state']>, string> = {
  pending_scan: 'Ожидает проверки',
  scanning: 'Проверяется',
  ready: 'Проверен',
  infected: 'Заблокирован (вирус)',
}

export const PDF_RU: Record<NonNullable<FileState['pdf_state']>, string> = {
  none: '—',
  converting: 'Конвертируется…',
  ready_pdf: 'PDF готов',
  convert_failed: 'Ошибка конвертации',
}

// Права (FR-102/129): подписи для карточки, матрицы переходов и снапшотов.
// Раньше дублировались в MaterialCard (RUS), TransitionMatrix (PERM_RU),
// PermissionsEditor (PERMISSIONS_RU) — с вариацией «Ревью»/«Ревью (утверждение)».
export const PERMISSIONS_RU: Record<string, string> = {
  view: 'Просмотр', create: 'Создание', edit: 'Редактирование', delete: 'Удаление',
  review: 'Ревью (утверждение)', publish: 'Публикация', archive: 'Архивация',
  copy: 'Копирование', move: 'Перемещение', download: 'Скачивание',
  manage_permissions: 'Управление правами',
}

// Типы событий уведомлений (11.1): раньше дублировались в NotificationBell
// (с file_blocked) и NotificationTriggers (без; статус «(общий)»).
export const EVENT_TITLES: Record<string, string> = {
  material_sent_to_review: 'Материал отправлен на проверку',
  material_rejected: 'Материал отклонён',
  material_archived: 'Материал заархивирован',
  child_auto_archived: 'Подчинённый материал архивирован автоматически',
  master_changed: 'Мастер-материал изменён',
  material_changed_on_review: 'Материал изменён на проверке',
  status_changed: 'Изменение статуса материала',
  file_blocked: 'Файл заблокирован антивирусом',
}

/** Дата/время в локали браузера (NFR-018: часовой пояс браузера). */
export function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' })
}

/** Компактный формат для таблиц (дата короткая, время среднее). */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'medium' })
}

/** Единый текст ошибки API для показа в интерфейсе. */
export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
