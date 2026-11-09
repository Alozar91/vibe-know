// Корпоративная база знаний — веб-клиент (SPA).
// Этап 4: вход (US-001), дерево групп + списки (US-005), разделы (US-006),
// карточка материала (US-037/031), снапшоты прав (US-044, СА).
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

type View = { kind: 'browser' } | { kind: 'sections' } | { kind: 'matrix' } | { kind: 'search'; q: string } | { kind: 'analytics' } | { kind: 'material'; id: string } | { kind: 'triggers' } | { kind: 'audit' } | { kind: 'settings' } | { kind: 'service' }

export default function App() {
  const [ready, setReady] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [view, setView] = useState<View>({ kind: 'browser' })
  const [refreshToken, setRefreshToken] = useState(0)
  const [me, setMe] = useState<{ display_name?: string; is_super?: boolean } | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const unread = useUnreadCount()

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

  if (!ready) return <main style={wrap}><p>Загрузка…</p></main>

  if (!authed || !getAccessToken()) {
    return (
      <main style={wrap}>
        <h1>Корпоративная база знаний</h1>
        <p>Вход выполняется через Keycloak (Authorization Code + PKCE).</p>
        <button onClick={() => login().catch(console.error)}>Войти</button>
      </main>
    )
  }

  return (
    <main style={{ ...wrap, maxWidth: 1100 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h1 style={{ fontSize: 22 }}>Корпоративная база знаний</h1>
        <span>
          <NotificationBell unread={unread} />
          {me?.display_name ?? '…'}{' '}
          {me?.is_super && <small style={{ background: '#333', color: '#fff', padding: '2px 6px', borderRadius: 4 }}>СА</small>}{' '}
          <button onClick={() => logout()}>Выйти</button>
        </span>
      </header>
      {/* Глобальный поиск в шапке — на всех страницах (FR-110, US-034) */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
               placeholder="Поиск…" style={{ flex: 1 }}
               onKeyDown={(e) => {
                 if (e.key === 'Enter') setView({ kind: 'search', q: searchQ })
               }} />
        <button onClick={() => setView({ kind: 'search', q: searchQ })}>Найти</button>
      </div>
      <nav style={{ marginBottom: 16, display: 'flex', gap: 8 }}>
        <button onClick={() => setView({ kind: 'browser' })}
                style={view.kind === 'browser' ? activeNav : {}}>
          Материалы
        </button>
        <button onClick={() => setView({ kind: 'sections' })}
                style={view.kind === 'sections' ? activeNav : {}}>
          Разделы
        </button>
        {me?.is_super && (
          <button onClick={() => setView({ kind: 'matrix' })}
                  style={view.kind === 'matrix' ? activeNav : {}}>
            Матрица переходов
          </button>
        )}
        {me?.is_super && (
          <button onClick={() => setView({ kind: 'analytics' })}
                  style={view.kind === 'analytics' ? activeNav : {}}>
            Аналитика поиска
          </button>
        )}
        {me?.is_super && (
          <button onClick={() => setView({ kind: 'triggers' })}
                  style={view.kind === 'triggers' ? activeNav : {}}>
            Настройка уведомлений
          </button>
        )}
        {me?.is_super && (
          <button onClick={() => setView({ kind: 'audit' })}
                  style={view.kind === 'audit' ? activeNav : {}}>
            Журнал аудита
          </button>
        )}
        {me?.is_super && (
          <button onClick={() => setView({ kind: 'settings' })}
                  style={view.kind === 'settings' ? activeNav : {}}>
            Параметры системы
          </button>
        )}
        {me?.is_super && (
          <button onClick={() => setView({ kind: 'service' })}
                  style={view.kind === 'service' ? activeNav : {}}>
            Служебный раздел
          </button>
        )}
      </nav>

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
  )
}

const wrap: React.CSSProperties = { fontFamily: 'system-ui, sans-serif', margin: '1.5rem auto', maxWidth: 900, padding: '0 1rem' }
const activeNav: React.CSSProperties = { fontWeight: 'bold', borderBottom: '2px solid #333' }
