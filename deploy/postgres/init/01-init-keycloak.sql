-- Инициализация экземпляра PostgreSQL (выполняется psql от имени POSTGRES_USER).
-- Отдельная БД для Keycloak внутри того же экземпляра (HLD §3.2, примечание).
CREATE DATABASE keycloak;
