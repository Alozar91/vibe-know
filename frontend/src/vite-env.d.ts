/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** База OIDC Keycloak для SPA (задаётся build-arg'ом nginx-образа; дефолт — локальный стенд) */
  readonly VITE_KC_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
