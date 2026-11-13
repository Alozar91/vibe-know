// Регресс-тест поиска из шапки (13.11.2026): Enter в шапке должен переводить
// на /search?q=... и запускать поиск. Два дефекта реорганизации:
//   1) setSearchParams({q}) менял query текущего маршрута (/?q=... вместо /search?q=...)
//   2) SearchView не запускал поиск автоматически при внешнем q
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '../../../App'
import { search } from '../../../api/search'

vi.mock('../../../api/search', () => ({
  search: vi.fn(async () => ({
    items: [{ id: 'm1', name: 'Регламент', status: 'active', updated_at: '2026-11-12T10:00:00Z' }],
    total: 1,
    page: 1,
    pages: 1,
    per_page: 50,
    groups: [],
    query: 'регламент',
    search_event_id: null,
  })),
  postSearchOpen: vi.fn(async () => undefined),
  getSearchAnalytics: vi.fn(),
}))

vi.mock('../../../api/client', () => ({
  api: vi.fn(async () => ({
    id: 'u1', display_name: 'Иван Иванов', is_super: true, roles: ['Системный администратор'],
  })),
  apiUpload: vi.fn(),
}))

// auth: считаем пользователя аутентифицированным
vi.mock('../../../shared/auth/auth', () => ({
  isAuthenticated: () => true,
  getAccessToken: () => 'test-token',
  ensureFreshToken: vi.fn(async () => undefined),
  completeLogin: vi.fn(async () => undefined),
  login: vi.fn(async () => undefined),
  logout: vi.fn(() => undefined),
  register: vi.fn(async () => undefined),
}))

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname}{loc.search}</div>
}

describe('поиск из шапки', () => {
  beforeEach(() => {
    vi.mocked(search).mockClear()
  })
  afterEach(cleanup)

  it('Enter в шапке → /search?q=... и авто-запуск поиска', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/']}>
          <App />
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const input = screen.getByPlaceholderText(/Поиск по материалам/)
    fireEvent.change(input, { target: { value: 'регламент' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/search?q=%D1%80%D0%B5%D0%B3%D0%BB%D0%B0%D0%BC%D0%B5%D0%BD%D1%82')
    })
    await waitFor(() => {
      expect(search).toHaveBeenCalled()
    })
    // Авто-выдача отображается без второго Enter
    await waitFor(() => {
      expect(screen.getByText(/Найдено/)).toBeInTheDocument()
    })
  })
})
