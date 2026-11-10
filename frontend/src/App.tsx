// Корпоративная база знаний — веб-клиент (SPA).
// Этап 4: вход (US-001), дерево групп + списки (US-005), разделы (US-006),
// карточка материала (US-037/031), снапшоты прав (US-044, СА).
// modern-ui: каркас шапка+сайдбар, темы light/dark (переключатель в шапке).
import { useEffect, useState } from 'react'
import { completeLogin, getAccessToken, isAuthenticated, login, logout, api } from './auth'
import MaterialsBrowser from './MaterialsBrowser'
import MaterialCardView from './MaterialCard'
import Sections from './Sections'
import PermissionsEditor from './PermissionsEditor'
import TransitionMatrix from './TransitionMatrix'
import SearchView from './SearchView'
import SearchAnalytics from './SearchAnalytics'
import NotificationBell, { useUnreadCount } from './NotificationBell'
import NotificationTriggers from './NotificationTriggers'
import AuditLog from './AuditLog'
import SystemSettings from './SystemSettings'
import ServiceDesk from './ServiceDesk'
import { applyTheme, loadTheme, type Theme } from './theme'
import './styles.css'

type View = { kind: 'browser' } | { kind: 'sections' } | { kind: 'matrix' } | { kind: 'search'; q: string } | { kind: 'analytics' } | { kind: 'material'; id: string } | { kind: 'triggers' } | { kind: 'audit' } | { kind: 'settings' } | { kind: 'service' }

const NAV = [
  { kind: 'browser', label: 'Материалы', icon: '📦', superOnly: false },
  { kind: 'sections', label: 'Разделы', icon: '🗂️', superOnly: false },
  { kind: 'matrix', label: 'Матрица переходов', icon: '🔀', superOnly: true },
  { kind: 'analytics', label: 'Аналитика поиска', icon: '📈', superOnly: true },
  { kind: 'triggers', label: 'Настройка уведомлений', icon: '🔔', superOnly: true },
  { kind: 'audit', label: 'Журнал аудита', icon: '🛡️', superOnly: true },
  { kind: 'settings', label: 'Параметры системы', icon: '⚙️', superOnly: true },
  { kind: 'service', label: 'Служебный раздел', icon: '🧰', superOnly: true },
] as const

// Инициалы для аватара: «Иван Иванов» → «ИИ»
function initials(name?: string): string {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  return parts.slice(0, 2).map((x) => x[0]?.toUpperCase() ?? '').join('')
}

export default function App() {
  const [ready, setReady] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [view, setView] = useState<View>({ kind: 'browser' })
  const [refreshToken, setRefreshToken] = useState(0)
  const [me, setMe] = useState<{ display_name?: string; is_super?: boolean } | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const [theme, setTheme] = useState<Theme>(loadTheme)
  const unread = useUnreadCount()

  useEffect(() => { applyTheme(theme) }, [theme])

  // Колокольчик: «открыть материал» из ленты уведомлений
  useEffect(() => {
    const h = (e: Event) => setView({ kind: 'material', id: (e as CustomEvent).detail as string })
    window.addEventListener('kb:open-material', h)
    return () => window.removeEventListener('kb:open-material', h)
  }, [])

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
    api<{ display_name: string; is_super?: boolean }>('/me')
      .then(setMe)
      .catch(() => setAuthed(false))
  }, [authed, refreshToken])

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
        </div>
      </div>
    )
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
            onKeyDown={(e) => { if (e.key === 'Enter') setView({ kind: 'search', q: searchQ }) }}
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
            <div className="role">{me?.is_super ? 'Системный администратор' : 'Пользователь'}</div>
          </div>
        </div>
        <button className="btn ghost small" onClick={() => logout()}>Выйти</button>
      </header>

      <div className="shell">
        <aside className="side">
          <h4>Разделы</h4>
          <nav className="nav">
            {NAV.filter((n) => !n.superOnly || me?.is_super).map((n) => (
              <button
                key={n.kind}
                className={`navi ${view.kind === n.kind ? 'on' : ''}`}
                onClick={() => setView({ kind: n.kind } as View)}
              >
                <span className="ni">{n.icon}</span> {n.label}
              </button>
            ))}
          </nav>
        </aside>

        <main className="content">
          {view.kind === 'browser' && (
            <MaterialsBrowser onOpenMaterial={(id) => setView({ kind: 'material', id })} refreshToken={refreshToken} />
          )}
          {view.kind === 'sections' && (
            <Sections onOpenMaterial={(id) => setView({ kind: 'material', id })} refreshToken={refreshToken} />
          )}
          {view.kind === 'matrix' && <TransitionMatrix />}
          {view.kind === 'analytics' && <SearchAnalytics />}
          {view.kind === 'triggers' && <NotificationTriggers />}
          {view.kind === 'audit' && <AuditLog />}
          {view.kind === 'settings' && <SystemSettings />}
          {view.kind === 'service' && <ServiceDesk />}
          {view.kind === 'search' && (
            <SearchView initialQuery={view.q} onOpenMaterial={(id) => setView({ kind: 'material', id })} />
          )}
          {view.kind === 'material' && (
            <>
              <MaterialCardView
                materialId={view.id}
                onSaved={() => setRefreshToken((x) => x + 1)}
                onClosed={() => setView({ kind: 'browser' })}
                onOpenCard={(id) => setView({ kind: 'material', id })}
              />
              {/* US-044: управление правами — только СА (FR-105); компонент сам получит 403 у не-СА */}
              <PermissionsEditor objectType="material" objectId={view.id} />
            </>
          )}
        </main>
      </div>
    </>
  )
}
