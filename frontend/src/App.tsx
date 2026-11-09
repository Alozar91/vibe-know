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

type View = { kind: 'browser' } | { kind: 'sections' } | { kind: 'matrix' } | { kind: 'material'; id: string }

export default function App() {
  const [ready, setReady] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [view, setView] = useState<View>({ kind: 'browser' })
  const [refreshToken, setRefreshToken] = useState(0)
  const [me, setMe] = useState<{ display_name?: string; is_super?: boolean } | null>(null)

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
          {me?.display_name ?? '…'}{' '}
          {me?.is_super && <small style={{ background: '#333', color: '#fff', padding: '2px 6px', borderRadius: 4 }}>СА</small>}{' '}
          <button onClick={() => logout()}>Выйти</button>
        </span>
      </header>
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
      </nav>

      {view.kind === 'browser' && (
        <MaterialsBrowser onOpenMaterial={(id) => setView({ kind: 'material', id })} refreshToken={refreshToken} />
      )}
      {view.kind === 'sections' && (
        <Sections onOpenMaterial={(id) => setView({ kind: 'material', id })} refreshToken={refreshToken} />
      )}
      {view.kind === 'matrix' && <TransitionMatrix />}
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
