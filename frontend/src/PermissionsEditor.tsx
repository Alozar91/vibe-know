// Управление снапшотами прав на объекте (US-044) — только СА (FR-105).
// Копия шаблона роли + состояния allow/deny/unset (FR-102).
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './auth'
import type { Role, Snapshot } from './types'

const PERMISSIONS_RU: Record<string, string> = {
  view: 'Просмотр', create: 'Создание', edit: 'Редактирование', delete: 'Удаление',
  review: 'Ревью (утверждение)', publish: 'Публикация', archive: 'Архивация',
  copy: 'Копирование', move: 'Перемещение', download: 'Скачивание',
  manage_permissions: 'Управление правами',
}

interface Props {
  objectType: 'group' | 'material'
  objectId: string
}

export default function PermissionsEditor({ objectType, objectId }: Props) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      setSnapshots(await api<Snapshot[]>(`/${objectType}s/${objectId}/permissions`))
      const r = await api<Role[] | { items: Role[] }>('/roles')
      setRoles(Array.isArray(r) ? r : r.items)
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }, [objectType, objectId])

  useEffect(() => {
    load()
  }, [load])

  async function copyFromRole(roleId: string) {
    try {
      await api(`/${objectType}s/${objectId}/permissions`, {
        method: 'POST',
        body: JSON.stringify({ role_id: roleId, entries: [] }), // копия состава шаблона (US-044 шаг 1)
      })
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  async function setState(snapshotId: string, permission: string, state: 'allow' | 'deny' | 'unset') {
    try {
      await api(`/permissions/snapshots/${snapshotId}`, {
        method: 'PATCH',
        body: JSON.stringify({ entries: [{ permission, state }] }),
      })
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  async function removeSnapshot(snapshotId: string) {
    if (!window.confirm('Удалить снапшот прав?')) return
    try {
      await api(`/permissions/snapshots/${snapshotId}`, { method: 'DELETE' })
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  const assignable = roles.filter((r) => !r.is_virtual_all_users)

  return (
    <div style={{ borderTop: '1px solid #ddd', marginTop: 24, paddingTop: 12 }}>
      <h3>Права доступа (снапшоты)</h3>
      {error && <p style={{ color: '#b00' }}>{error}</p>}

      {assignable.length > 0 && (
        <p>
          Скопировать права из шаблона:{' '}
          {assignable.map((r) => (
            <button key={r.id} onClick={() => copyFromRole(r.id)} style={{ marginRight: 6 }}>
              {r.name}
            </button>
          ))}
        </p>
      )}

      {snapshots.length === 0 && <p style={{ color: '#777' }}>Снапшотов нет — доступ запрещён (default deny)</p>}
      {snapshots.map((s) => (
        <div key={s.id} style={{ border: '1px solid #eee', borderRadius: 6, padding: 10, marginBottom: 10 }}>
          <b>{s.role_name}</b>{' '}
          <button onClick={() => removeSnapshot(s.id)} style={{ float: 'right', color: '#b00' }}>Удалить</button>
          <table style={{ borderCollapse: 'collapse', marginTop: 8 }}>
            <tbody>
              {s.entries.map((e) => (
                <tr key={e.permission}>
                  <td style={{ padding: '2px 12px 2px 0' }}>{PERMISSIONS_RU[e.permission] ?? e.permission}</td>
                  <td style={{ padding: '2px 12px' }}>{e.state === 'allow' ? '✓ Разрешить' : '✗ Запретить'}</td>
                  <td style={{ padding: 2 }}>
                    {e.state !== 'allow' && <button onClick={() => setState(s.id, e.permission, 'allow')}>Разрешить</button>}
                    {e.state !== 'deny' && <button onClick={() => setState(s.id, e.permission, 'deny')}>Запретить</button>}
                    <button onClick={() => setState(s.id, e.permission, 'unset')}>Не задано</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
