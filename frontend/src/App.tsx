// Корпоративная база знаний — веб-клиент (SPA).
// Этап 4: вход (US-001), дерево групп + списки (US-005), разделы (US-006),
// карточка материала (US-037/031), снапшоты прав (US-044, СА).
// modern-ui: каркас шапка+сайдбар, темы light/dark (переключатель в шапке).
import { useEffect, useState } from 'react'
import { completeLogin, getAccessToken, isAuthenticated, login, logout, api, register } from './auth'
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

// Оффер тестовой регистрации (НЕ для продуктива): состояние + допустимые роли
interface TestOffer {
  enabled: boolean
  available: boolean
  roles: { id: string; name: string }[]
}

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

// Экран выбора роли тестовой регистрации (одноразовый, после первого входа).
// Показывается, только когда флаг включён и ролей у пользователя ещё нет.
function RolePicker({ onDone }: { onDone: (dismiss?: boolean) => void }) {
  const [offer, setOffer] = useState<TestOffer | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  useEffect(() => {
    api<TestOffer>('/me/test-registration')
      .then(setOffer)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  async function choose(roleId: string) {
    setError('')
    setBusy(roleId)
    try {
      await api('/me/test-registration', { method: 'POST', body: JSON.stringify({ role_id: roleId }) })
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy('')
    }
  }

  if (error) {
    return (
      <div className="rolepick">
        <div className="box">
          <div className="logo mark">БЗ</div>
          <h2>Не удалось загрузить выбор роли</h2>
          <p className="note">{error}</p>
          <button className="btn primary" onClick={() => onDone(true)}>Продолжить без выбора</button>
        </div>
      </div>
    )
  }
  if (!offer) {
    return <div className="rolepick"><div className="box"><p className="spin">Загрузка…</p></div></div>
  }
  if (!offer.available) {
    return (
      <div className="rolepick">
        <div className="box">
          <div className="logo mark">БЗ</div>
          <h2>Роль уже назначена</h2>
          <p className="note">Выбор роли доступен один раз; смену роли выполняет системный администратор.</p>
          <button className="btn primary" onClick={() => onDone(true)}>Продолжить</button>
        </div>
      </div>
    )
  }
  return (
    <div className="rolepick">
      <div className="box wide">
        <div className="logo mark">БЗ</div>
        <h2>Выберите роль для тестирования</h2>
        <p className="note">
          Тестовый режим: роль определяет права в системе. Выбор одноразовый —
          потом роль может поменять только системный администратор.
        </p>
        {error && <div className="alert err">{error}</div>}
        <div className="rp-grid">
          {offer.roles.map((r) => (
            <button
              key={r.id}
              className="rp-card"
              disabled={!!busy}
              onClick={() => choose(r.id)}
            >
              <div className="rp-name">{r.name}</div>
              <div className="rp-desc">{ROLE_HINTS[r.name] ?? 'Просмотр материалов'}</div>
              <div className="rp-go">{busy === r.id ? 'Назначение…' : 'Выбрать →'}</div>
            </button>
          ))}
        </div>
        <button className="btn ghost small rp-later" onClick={() => onDone(true)}>Пока не выбирать</button>
        <a className="rp-escape" href="" onClick={(e) => { e.preventDefault(); register().catch(console.error) }}>
          Зарегистрировать нового пользователя (тест)
        </a>
      </div>
    </div>
  )
}

// Подсказки по ролям (сид LLD §2.6; для клонов — общий текст)
const ROLE_HINTS: Record<string, string> = {
  'Читатель': 'Просмотр опубликованных материалов',
  'Автор': 'Создание и редактирование своих материалов',
  'Рецензент': 'Проверка материалов на проверке',
  'Публикатор': 'Публикация и архивация материалов',
}

export default function App() {
  const [ready, setReady] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [view, setView] = useState<View>({ kind: 'browser' })
  const [refreshToken, setRefreshToken] = useState(0)
  const [me, setMe] = useState<{ display_name?: string; is_super?: boolean; roles?: string[] } | null>(null)
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
    api<{ display_name: string; is_super?: boolean; roles?: string[] }>('/me')
      .then(setMe)
      .catch(() => setAuthed(false))
  }, [authed, refreshToken])

  // Перезагрузить /me после закрытия экрана тестовой регистрации.
  // «Пока не выбирать» запоминается на сессию вкладки: без роли пользователь
  // видит систему в объёме default deny (§3.2), выбор можно продолжить позже.
  function afterRoleChoice(dismiss = false) {
    if (dismiss) sessionStorage.setItem('kb-rolepick-dismissed', '1')
    setMe(null)
    setAuthed(false)
    setTimeout(() => setAuthed(isAuthenticated()), 0)
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
  // «Пока не выбирать» гасит экран до конца сессии вкладки (sessionStorage)
  if (me && !me.is_super && (me.roles ?? []).length === 0 && !sessionStorage.getItem('kb-rolepick-dismissed')) {
    return <RolePicker onDone={afterRoleChoice} />
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
