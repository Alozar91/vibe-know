// ESLint (flat config): TypeScript strict + правила хуков React.
// Реорганизация frontend: инфраструктура качества кода.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'node_modules'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Отключено осознанно: карточка материала (useMaterialCard) использует
      // управляемую загрузку нескольких эндпоинтов с последующим setState
      // (оркестрация обновлений после мутаций); списочные экраны постепенно
      // переезжают на TanStack Query, где правило не применимо.
      'react-hooks/set-state-in-effect': 'off',
      'react-refresh/only-export-components': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
)
