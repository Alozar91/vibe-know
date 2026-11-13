// API-клиент: Bearer + problem+json (LLD §12.1).
// Реорганизация frontend: вынесен из auth.ts — auth остаётся только OIDC-протоколом;
// здесь — транспорт (fetch, токен, разбор ошибок problem+json).
// Доменные функции — в соседних файлах (materials.ts, groups.ts, search.ts, ...):
// компоненты не вызывают api()/fetch напрямую.
import { ensureFreshToken, getAccessToken } from '../shared/auth/auth'

export class ApiError extends Error {
  constructor(public status: number, public code: string, public title: string,
              public detail?: string, public params?: Record<string, unknown>) {
    super(detail ?? title)
  }
}

export async function api<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  if (!getAccessToken()) throw new ApiError(401, 'NO_TOKEN', 'Не выполнен вход')
  await ensureFreshToken()
  const r = await fetch(`/api/v1${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getAccessToken()}`,
      ...(opts.headers ?? {}),
    },
  })
  if (r.status === 204) return undefined as T
  const ct = r.headers.get('content-type') ?? ''
  const body = ct.includes('json') ? await r.json() : await r.text()
  if (!r.ok) {
    const p = (body ?? {}) as Record<string, unknown>
    throw new ApiError(r.status,
                       (p.code as string) ?? 'HTTP_ERROR',
                       (p.title as string) ?? 'Ошибка',
                       p.detail as string | undefined,
                       p.params as Record<string, unknown> | undefined)
  }
  return body as T
}

// multipart-загрузка (этап 6, §6.2): Content-Type ставит браузер (boundary)
export async function apiUpload<T = unknown>(path: string, file: File, query = ''): Promise<T> {
  if (!getAccessToken()) throw new ApiError(401, 'NO_TOKEN', 'Не выполнен вход')
  await ensureFreshToken()
  const form = new FormData()
  form.append('file', file)
  const r = await fetch(`/api/v1${path}${query}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getAccessToken()}` },
    body: form,
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    const p = (body ?? {}) as Record<string, unknown>
    throw new ApiError(r.status,
                       (p.code as string) ?? 'HTTP_ERROR',
                       (p.title as string) ?? 'Ошибка',
                       p.detail as string | undefined,
                       p.params as Record<string, unknown> | undefined)
  }
  return body as T
}

// авторизованное скачивание/предпросмотр (этап 6, §6.4): Bearer — в fetch,
// не в <img src>/<a href> (браузер к silo не обращается — api-стриминг)
export async function apiDownload(path: string): Promise<Response> {
  if (!getAccessToken()) throw new ApiError(401, 'NO_TOKEN', 'Не выполнен вход')
  await ensureFreshToken()
  return fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${getAccessToken()}` },
  })
}
