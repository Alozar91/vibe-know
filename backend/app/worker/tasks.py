# Реестр задач Celery (имена — точно по LLD §9).
# Этап 1: реестр пуст; задачи добавляются по этапам:
#   6: files.scan, files.convert
#   9: notifications.dispatch, notifications.email, notifications.digest
#   10: maintenance.audit_cleanup, maintenance.inapp_cleanup, maintenance.analytics_rollup,
#       maintenance.cas_gc, maintenance.cas_reconcile, keycloak.sync,
#       maintenance.integrity_check, maintenance.fts_rebuild
