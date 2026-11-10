// Переключатель темы (modern-ui): светлая «Консоль» ↔ тёмная.
// Выбор сохраняется в localStorage; по умолчанию — светлая.
export type Theme = 'light' | 'dark'

const KEY = 'kb-theme'

export function loadTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function applyTheme(t: Theme): void {
  const root = document.documentElement
  root.classList.remove('theme-light', 'theme-dark')
  root.classList.add(t === 'dark' ? 'theme-dark' : 'theme-light')
  try {
    localStorage.setItem(KEY, t)
  } catch {
    /* приватный режим — тема не сохранится */
  }
}
