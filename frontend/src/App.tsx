// Корпоративная база знаний — веб-клиент (SPA).
// Этап 4: вход (US-001), дерево групп + списки (US-005), разделы (US-006),
// карточка материала (US-037/031), снапшоты прав (US-044, СА).
// modern-ui: каркас шапка+сайдбар, темы light/dark (переключатель в шапке).
//
// Реорганизация frontend: навигация — react-router (deep links: F5 сохраняет
// экран, карточка материала открывается по URL /materials/:id); маршруты:
//   /                 — материалы (браузер групп, US-005)
//   /materials/:id    — карточка материала (US-037) + права (US-044)
//   /sections         — разделы (US-006)
//   /search?q=        — поиск (US-034–036)
//   /matrix | /analytics | /triggers | /audit | /settings | /service | /rag — СА
import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { completeLogin, getAccessToken, isAuthenticated, login, logout, register } from './shared/auth/auth'
import { api } from './api/client'
import MaterialsBrowser from './features/materials/components/MaterialsBrowser'
import MaterialCardView from './features/materials/components/MaterialCardView'
import Sections from './features/materials/components/Sections'
import PermissionsEditor from './features/admin/components/PermissionsEditor'
import TransitionMatrix from './features/admin/components/TransitionMatrix'
import SearchView from './features/search/components/SearchView'
import SearchAnalytics from './features/search/components/SearchAnalytics'
import NotificationBell, { useUnreadCount } from './features/notifications/components/NotificationBell'
import NotificationTriggers from './features/admin/components/NotificationTriggers'
import AuditLog from './features/admin/components/AuditLog'
import SystemSettings from './features/admin/components/SystemSettings'
import ServiceDesk from './features/admin/components/ServiceDesk'
import RagAdmin from './features/admin/components/RagAdmin'
import RolePicker from './features/auth/components/RolePicker'
import { applyTheme, loadTheme, type Theme } from './shared/theme/theme'
import './styles.css'

// Оффер тестовой регистрации — в features/auth/components/RolePicker.tsx

const NAV = [
  { path: '/', label: 'Материалы', icon: '📦', superOnly: false },
  { path: '/sections', label: 'Разделы', icon: '🗂️', superOnly: false },
  { path: '/matrix', label: 'Матрица переходов', icon: '🔀', superOnly: true },
  { path: '/analytics', label: 'Аналитика поиска', icon: '📈', superOnly: true },
  { path: '/triggers', label: 'Настройка уведомлений', icon: '🔔', superOnly: true },
  { path: '/audit', label: 'Журнал аудита', icon: '🛡️', superOnly: true },
  { path: '/settings', label: 'Параметры системы', icon: '⚙️', superOnly: true },
  { path: '/service', label: 'Служебный раздел', icon: '🧰', superOnly: true },
  { path: '/rag', label: 'RAG — векторный поиск', icon: '🧠', superOnly: true },
] as const

// Инициалы для аватара: «Иван Иванов» → «ИИ»
function initials(name?: string): string {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  return parts.slice(0, 2).map((x) => x[0]?.toUpperCase() ?? '').join('')
}

// Страница карточки: /materials/:id + права (US-044). Компонент-обёртка,
// чтобы useParams был рядом с маршрутом.
function MaterialPage({ onSaved }: { onSaved: () => void }) {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  if (!id) return null
  return (
    <>
      <MaterialCardView
        materialId={id}
        onSaved={onSaved}
        onClosed={() => navigate(-1)}
        onOpenCard={(mid) => navigate(`/materials/${mid}`)}
      />
      {/* US-044: управление правами — только СА (FR-105); компонент сам получит 403 у не-СА */}
      <PermissionsEditor objectType="material" objectId={id} />
    </>
  )
}

export default function App() {
  const [ready, setReady] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [refreshToken, setRefreshToken] = useState(0)
  const [me, setMe] = useState<{ id?: string; display_name?: string; is_super?: boolean; roles?: string[] } | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const [theme, setTheme] = useState<Theme>(loadTheme)
  const unread = useUnreadCount()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  useEffect(() => { applyTheme(theme) }, [theme])

  // Колокольчик: «открыть материал» из ленты уведомлений → deep link
  useEffect(() => {
    const h = (e: Event) => navigate(`/materials/${(e as CustomEvent).detail as string}`)
    window.addEventListener('kb:open-material', h)
    return () => window.removeEventListener('kb:open-material', h)
  }, [navigate])

  useEffect(() => {
    (async () => {
      if (new URLSearchParams(window.location.search).get('code')) {
        await completeLogin()
      }
      setAuthed(isAuthenticated())
      setReady(true)
    })()
  }, [])

  useEffect(() => {
    if (!authed) return
    api<{ id?: string; display_name: string; is_super?: boolean; roles?: string[] }>('/me')
      .then(setMe)
      .catch(() => setAuthed(false))
  }, [authed, refreshToken])

  // Перезагрузить /me после закрытия экрана тестовой регистрации.
  // «Пока не выбирать» запоминается на сессию вкладки (sessionStorage) и
  // привязано к пользователю (ключ с user_id) — иначе флаг одной проверки
  // погасит оффер другому пользователю, вошедшему в той же вкладке.
  function afterRoleChoice(dismiss = false) {
    if (dismiss && me?.id) sessionStorage.setItem(`kb-rolepick-dismissed:${me.id}`, '1')
    setRefreshToken((x) => x + 1)
  }

  if (!ready) {
    return (
      <div className="login">
        <div className="box"><p>Загрузка…</p></div>
      </div>
    )
  }

  if (!authed || !getAccessToken()) {
    return (
      <div className="login">
        <div className="box">
          <div className="logo mark" style={{ margin: '0 auto 14px' }}>БЗ</div>
          <h2>Корпоративная база знаний</h2>
          <p className="note">Вход выполняется через Keycloak (Authorization Code + PKCE).</p>
          <button className="btn primary" onClick={() => login().catch(console.error)}>Войти</button>
          <div className="login-links">
            <a href="" onClick={(e) => { e.preventDefault(); register().catch(console.error) }}>
              Зарегистрироваться (тест)
            </a>
          </div>
        </div>
      </div>
    )
  }

  // Тестовая регистрация (НЕ для продуктива): пока у пользователя нет ролей,
  // показываем одноразовый экран выбора роли (флаг проверит GET-оффер).
  // «Пока не выбирать» гасит экран до конца сессии вкладки — ключ флага
  // привязан к пользователю (см. afterRoleChoice).
  if (me?.id && !me.is_super && (me.roles ?? []).length === 0
      && !sessionStorage.getItem(`kb-rolepick-dismissed:${me.id}`)) {
    return <RolePicker onDone={afterRoleChoice} />
  }

  // Поиск из шапки: q — параметр URL (deep link на выдачу)
  function headerSearch(q: string) {
    setSearchParams({ q })
  }

  return (
    <>
      <header className="topbar">
        <div className="logo"><div className="mark">БЗ</div> Корпоративная база знаний</div>
        {/* Глобальный поиск в шапке — на всех страницах (FR-110, US-034) */}
        <div className="gsearch">
          <span className="ico">🔍</span>
          <input
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder="Поиск по материалам… (Enter)"
            onKeyDown={(e) => { if (e.key === 'Enter') headerSearch(searchQ) }}
          />
        </div>
        <div className="spacer" />
        <button
          className="iconbtn"
          title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
        <NotificationBell unread={unread} />
        <div className="who">
          <div className="avatar">{initials(me?.display_name)}</div>
          <div>
            <div className="name">
              {me?.display_name ?? '…'} {me?.is_super && <span className="sa-badge">СА</span>}
            </div>
            <div className="role">{me?.is_super ? 'Системный администратор' : (me?.roles ?? [])[0] ?? 'Пользователь'}</div>
          </div>
        </div>
        <button className="btn ghost small" onClick={() => logout()}>Выйти</button>
      </header>

      <div className="shell">
        <aside className="side">
          <h4>Разделы</h4>
          <nav className="nav">
            {NAV.filter((n) => !n.superOnly || me?.is_super).map((n) => (
              <NavLink
                key={n.path}
                to={n.path}
                end={n.path === '/'}
                className={({ isActive }) => `navi ${isActive ? 'on' : ''}`}
              >
                <span className="ni">{n.icon}</span> {n.label}
              </NavLink>
            ))}
          </nav>
        </aside>

        <main className="content">
          <Routes>
            <Route path="/" element={<MaterialsBrowser onOpenMaterial={(id) => navigate(`/materials/${id}`)} refreshToken={refreshToken} isSuper={!!me?.is_super} />} />
            <Route path="/materials/:id" element={<MaterialPage onSaved={() => setRefreshToken((x) => x + 1)} />} />
            <Route path="/sections" element={<Sections onOpenMaterial={(id) => navigate(`/materials/${id}`)} refreshToken={refreshToken} />} />
            <Route path="/search" element={<SearchView initialQuery={searchParams.get('q') ?? ''} onOpenMaterial={(id) => navigate(`/materials/${id}`)} />} />
            <Route path="/matrix" element={<TransitionMatrix />} />
            <Route path="/analytics" element={<SearchAnalytics />} />
            <Route path="/triggers" element={<NotificationTriggers />} />
            <Route path="/audit" element={<AuditLog />} />
            <Route path="/settings" element={<SystemSettings />} />
            <Route path="/service" element={<ServiceDesk />} />
            <Route path="/rag" element={<RagAdmin onOpenMaterial={(id) => navigate(`/materials/${id}`)} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </>
  )
}
