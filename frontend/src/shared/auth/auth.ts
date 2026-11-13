// Аутентификация SPA: Authorization Code + PKCE (HLD §6.1, LLD §10).
// Клиент kb-spa (public, S256); токены — в памяти (не localStorage), refresh-токен.
// Keycloak 26: /realms/kb/... ; при внедрении (шаг [6]) — /auth/... за nginx TLS
// (инструкция deploy/README.md, FR-149).
//
// Реорганизация frontend: этот модуль — только OIDC-протокол и хранение токенов;
// HTTP-клиент API вынесен в src/api/client.ts (берёт токен отсюда).

const KC_BASE: string =
  import.meta.env.VITE_KC_BASE ?? 'http://localhost:8080/realms/kb'
const CLIENT_ID = 'kb-spa'
const REDIRECT_URI = window.location.origin + window.location.pathname
// webOrigins realm: localhost, localhost:5173 + origin стенда (KB_PUBLIC_URL)

export interface Tokens {
  access_token: string
  refresh_token?: string
  id_token?: string // для id_token_hint при выходе (OIDC RP-Initiated Logout)
  expires_at: number // monotonic-ish: Date.now() + expires_in*1000
}

let tokens: Tokens | null = null
let refreshTimer: ReturnType<typeof setTimeout> | null = null

function b64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// PKCE: S256 (crypto.subtle — только secure context: HTTPS или localhost);
// на http://домен subtle недоступен — fallback на plain (RFC 7636 §4.2:
// challenge = verifier; Keycloak 26 поддерживает). При включении TLS (FR-149)
// S256 восстановится автоматически — secure context вернётся.
async function pkcePair(verifier: string): Promise<{ challenge: string; method: 'S256' | 'plain' }> {
  if (typeof crypto.subtle !== 'undefined') {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
    return { challenge: b64url(new Uint8Array(digest)), method: 'S256' }
  }
  return { challenge: verifier, method: 'plain' }
}

export async function login(): Promise<void> {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)))
  const { challenge, method } = await pkcePair(verifier)
  sessionStorage.setItem('pkce_verifier', verifier)
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: 'code',
    scope: 'openid profile email',
    code_challenge: challenge,
    code_challenge_method: method,
  })
  window.location.href = `${KC_BASE}/protocol/openid-connect/auth?${params}`
}

function logoutRedirect(): void {
  // OIDC RP-Initiated Logout: при post_logout_redirect_uri Keycloak 26 требует
  // id_token_hint — иначе ошибка «Missing parameters: id_token_hint».
  // id_token держится в памяти вместе с access/refresh (не в localStorage).
  const params = new URLSearchParams()
  if (tokens?.id_token) {
    params.set('id_token_hint', tokens.id_token)
    params.set('post_logout_redirect_uri', REDIRECT_URI)
  } else {
    // id_token нет (сессия уже истекла) — выход по SSO-сессии Keycloak без редиректа
  }
  window.location.href = `${KC_BASE}/protocol/openid-connect/logout?${params}`
}

export async function completeLogin(): Promise<boolean> {
  const q = new URLSearchParams(window.location.search)
  const code = q.get('code')
  const err = q.get('error')
  if (err) {
    console.error('KC error:', q.get('error_description'))
    return false
  }
  if (!code) return false
  const verifier = sessionStorage.getItem('pkce_verifier')
  if (!verifier) return false

  sessionStorage.removeItem('pkce_verifier')

  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    code,
    code_verifier: verifier,
  })
  const r = await fetch(`${KC_BASE}/protocol/openid-connect/token`, { method: 'POST', body })
  if (!r.ok) return false
  const j = await r.json()
  setTokens(j)
  return true
}

function setTokens(j: Record<string, unknown>): void {
  tokens = {
    access_token: j.access_token as string,
    refresh_token: j.refresh_token as string | undefined,
    // id_token нужен только для выхода (id_token_hint); при refresh — обновляется
    id_token: (j.id_token as string | undefined) ?? tokens?.id_token,
    expires_at: Date.now() + ((j.expires_in as number) - 30) * 1000, // запас 30 с
  }
  if (tokens!.refresh_token) scheduleRefresh((j.refresh_expires_in as number) ?? 1800)
}

function scheduleRefresh(refreshExpiresIn: number): void {
  if (refreshTimer) clearTimeout(refreshTimer)
  // обновление access-токена заранее; полная релогинизация при истечении refresh
  const delay = Math.max(60, refreshExpiresIn / 2) * 1000
  refreshTimer = setTimeout(tryRefresh, delay)
}

async function tryRefresh(): Promise<void> {
  if (!tokens?.refresh_token) return
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    client_id: CLIENT_ID,
    refresh_token: tokens.refresh_token,
  })
  const r = await fetch(`${KC_BASE}/protocol/openid-connect/token`, { method: 'POST', body })
  if (r.ok) {
    setTokens(await r.json())
  } else {
    logoutRedirect()
  }
}

// Проактивное обновление access-токена перед запросом к API (вызывает
// src/api/client.ts перед каждым fetch; раньше эта логика была в auth.ts).
export async function ensureFreshToken(): Promise<void> {
  if (tokens && Date.now() > tokens.expires_at && tokens.refresh_token) await tryRefresh()
}

export function getAccessToken(): string | null {
  return tokens?.access_token ?? null
}

export function isAuthenticated(): boolean {
  return tokens !== null
}

export function logout(): void {
  logoutRedirect()
}

// Тестовая регистрация (НЕ для продуктива): auth-запрос с kc_action=register —
// Keycloak 26 показывает встроенную форму регистрации, после чего продолжает
// вход и возвращает code в SPA (completeLogin). Прямой URL /login-actions/
// registrations без контекста аутентификации даёт «Page not found».
export async function register(): Promise<void> {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)))
  const { challenge, method } = await pkcePair(verifier)
  sessionStorage.setItem('pkce_verifier', verifier)
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: 'code',
    scope: 'openid profile email',
    code_challenge: challenge,
    code_challenge_method: method,
    kc_action: 'register',
  })
  window.location.href = `${KC_BASE}/protocol/openid-connect/auth?${params}`
}
