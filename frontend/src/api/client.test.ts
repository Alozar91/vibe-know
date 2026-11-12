// Тесты API-клиента: Bearer-заголовки, разбор problem+json, 204.
// Реорганизация frontend: инфраструктура тестов (vitest + testing-library).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, apiUpload } from './client'
import { ensureFreshToken, getAccessToken, isAuthenticated } from '../shared/auth/auth'

// Мок модуля auth: управляем токенами без реального Keycloak
vi.mock('../shared/auth/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../shared/auth/auth')>()
  return {
    ...actual,
    ensureFreshToken: vi.fn(async () => undefined),
    getAccessToken: vi.fn(() => 'test-token'),
  }
})

const mockedGet = vi.mocked(getAccessToken)

describe('api client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    mockedGet.mockReturnValue('test-token')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('добавляет Bearer и Content-Type, парсит JSON', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ ok: 1 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    const r = await api<{ ok: number }>('/materials')
    expect(r).toEqual({ ok: 1 })
    expect(fetch).toHaveBeenCalledWith('/api/v1/materials', expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer test-token',
        'Content-Type': 'application/json',
      }),
    }))
  })

  it('204 возвращает undefined без разбора тела', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    const r = await api('/materials/1', { method: 'DELETE' })
    expect(r).toBeUndefined()
  })

  it('ошибка problem+json → ApiError с code/title/detail', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({
      code: 'VERSION_CONFLICT', title: 'Конфликт версий', detail: 'обновите карточку',
    }), {
      status: 412,
      headers: { 'content-type': 'application/problem+json' },
    }))
    await expect(api('/materials/1', { method: 'PATCH' })).rejects.toMatchObject({
      status: 412,
      code: 'VERSION_CONFLICT',
      title: 'Конфликт версий',
      detail: 'обновите карточку',
    })
  })

  it('ошибка без тела → HTTP_ERROR', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('server exploded', {
      status: 500,
      headers: { 'content-type': 'text/plain' },
    }))
    const err = await api('/materials').catch((e: unknown) => e as ApiError)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe('HTTP_ERROR')
  })

  it('без токена — NO_TOKEN, fetch не вызывается', async () => {
    mockedGet.mockReturnValueOnce(null)
    await expect(api('/materials')).rejects.toMatchObject({ code: 'NO_TOKEN', status: 401 })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('apiUpload отправляет FormData с file', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ file_state: {} }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    const f = new File(['x'], 'a.txt', { type: 'text/plain' })
    await apiUpload('/materials/1/file', f)
    const call = vi.mocked(fetch).mock.calls[0]
    expect(String(call[0])).toBe('/api/v1/materials/1/file')
    const init = call[1] as RequestInit
    expect(init.body).toBeInstanceOf(FormData)
  })
})

describe('auth helpers', () => {
  it('isAuthenticated определяется моком', () => {
    expect(typeof isAuthenticated()).toBe('boolean')
    expect(typeof ensureFreshToken).toBe('function')
  })
})
