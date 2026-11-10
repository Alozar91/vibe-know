-- Чистка стенда: контентные данные (в т.ч. нагрузочный корпус) + пользователи + группы.
-- Один общий TRUNCATE: FK-циклы (materials↔users↔permission_snapshots,
-- attribute_values→attributes/dictionaries, material_tags→tags, search_opens→materials)
-- не дают чистить таблицы по отдельности.
-- Сохраняются (сид системы): roles + role_permissions, transition_rules +
-- transition_rule_permissions, system_settings, notification_trigger_configs.
-- После чистки выполнить: python seed_demo.py (см. README §7).
BEGIN;

TRUNCATE attribute_values, attribute_type_bindings, comments, status_log,
         material_tags, material_versions, materials,
         search_opens, search_events, search_analytics,
         notifications, notification_events,
         file_objects, tags,
         material_types, attributes, dictionary_values, dictionaries,
         permission_entries, permission_snapshots,
         users, user_roles,
         service_tasks, system_tasks,
         audit_entries,
         groups;

COMMIT;

-- Контроль: несистемные таблицы пусты, системные сиды на месте
SELECT 'users' t, COUNT(*) FROM users
UNION ALL SELECT 'user_roles', COUNT(*) FROM user_roles
UNION ALL SELECT 'materials', COUNT(*) FROM materials
UNION ALL SELECT 'groups', COUNT(*) FROM groups
UNION ALL SELECT 'material_versions', COUNT(*) FROM material_versions
UNION ALL SELECT 'file_objects', COUNT(*) FROM file_objects
UNION ALL SELECT 'audit_entries', COUNT(*) FROM audit_entries
UNION ALL SELECT 'dictionaries', COUNT(*) FROM dictionaries
UNION ALL SELECT 'attributes', COUNT(*) FROM attributes
UNION ALL SELECT 'material_types', COUNT(*) FROM material_types
UNION ALL SELECT 'tags', COUNT(*) FROM tags
UNION ALL SELECT 'roles(сохранены)', COUNT(*) FROM roles
UNION ALL SELECT 'system_settings(сохранены)', COUNT(*) FROM system_settings
UNION ALL SELECT 'transition_rules(сохранены)', COUNT(*) FROM transition_rules
UNION ALL SELECT 'triggers(сохранены)', COUNT(*) FROM notification_trigger_configs
ORDER BY 1;
