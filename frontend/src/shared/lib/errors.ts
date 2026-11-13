// Ошибки: единый текст для показа в интерфейсе.
// Реорганизация frontend: раньше паттерн `${e.title}: ${e.detail ?? ''}`
// повторялся в каждом компоненте, а errText — трижды с вариациями.
import { ApiError } from '../../api/client'

/** Единый текст ошибки API для показа в интерфейсе. */
export function errText(e: unknown): string {
  if (e instanceof ApiError) return [e.title, e.detail].filter(Boolean).join(': ')
  return e instanceof Error ? e.message : String(e)
}

/** Текст конфликта версий (FR-095) или null, если ошибка другая.
 *  Раньше блок VERSION_CONFLICT дублировался ≥4 раз в MaterialCard. */
export function versionConflictText(e: unknown): string | null {
  return e instanceof ApiError && e.code === 'VERSION_CONFLICT'
    ? 'Материал изменён другим пользователем. Обновите карточку и повторите.'
    : null
}
