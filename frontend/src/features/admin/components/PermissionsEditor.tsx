// Управление снапшотами прав на объекте (US-044) — только СА (FR-105).
// Копия шаблона роли + состояния allow/deny/unset (FR-102).
// Реорганизация frontend: вызовы — через src/api/admin.
import { useCallback, useEffect, useState } from 'react'
import {
  copyRolePermissions, deletePermissionSnapshot, getPermissions, getRoles, setPermissionState,
} from '../../../api/admin'
import { PERMISSIONS_RU, errText } from '../../../shared/lib/dicts'
import { Empty, Err } from '../../../shared/ui/index'
import type { Role, Snapshot } from '../../../shared/types'

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
      setSnapshots(await getPermissions(objectType, objectId))
      setRoles(await getRoles())
    } catch (e) {
      setError(errText(e))
    }
  }, [objectType, objectId])

  useEffect(() => {
    void load()
  }, [load])

  async function copyFromRole(roleId: string) {
    try {
      await copyRolePermissions(objectType, objectId, roleId)
      await load()
    } catch (e) {
      setError(errText(e))
    }
  }

  async function setState(snapshotId: string, permission: string, state: 'allow' | 'deny' | 'unset') {
    try {
      await setPermissionState(snapshotId, permission, state)
      await load()
    } catch (e) {
      setError(errText(e))
    }
  }

  async function removeSnapshot(snapshotId: string) {
    if (!window.confirm('Удалить снапшот прав?')) return
    try {
      await deletePermissionSnapshot(snapshotId)
      await load()
    } catch (e) {
      setError(errText(e))
    }
  }

  const assignable = roles.filter((r) => !r.is_virtual_all_users)

  return (
    <div className="permbox">
      <h3>Права доступа (снапшоты)</h3>
      <Err>{error}</Err>

      {assignable.length > 0 && (
        <div className="btnrow">
          <span className="note">Скопировать права из шаблона:</span>
          {assignable.map((r) => (
            <button key={r.id} className="btn small ghost" onClick={() => void copyFromRole(r.id)}>
              {r.name}
            </button>
          ))}
        </div>
      )}

      {snapshots.length === 0 && <Empty>Снапшотов нет — доступ запрещён (default deny)</Empty>}
      {snapshots.map((s) => (
        <div key={s.id} className="panel" style={{ marginBottom: 10 }}>
          <div className="toolbar">
            <strong style={{ fontSize: 13 }}>{s.role_name}</strong>
            <span className="spacer" />
            <button className="btn danger small" onClick={() => void removeSnapshot(s.id)}>Удалить</button>
          </div>
          <table className="tbl">
            <tbody>
              {s.entries.map((e) => (
                <tr key={e.permission}>
                  <td style={{ width: '30%' }}>{PERMISSIONS_RU[e.permission] ?? e.permission}</td>
                  <td>
                    {e.state === 'allow'
                      ? <span className="badge b-published">Разрешить</span>
                      : <span className="badge b-archived">Запретить</span>}
                  </td>
                  <td className="btnrow" style={{ margin: 0 }}>
                    {e.state !== 'allow' && <button className="btn small" onClick={() => void setState(s.id, e.permission, 'allow')}>Разрешить</button>}
                    {e.state !== 'deny' && <button className="btn small" onClick={() => void setState(s.id, e.permission, 'deny')}>Запретить</button>}
                    <button className="btn small ghost" onClick={() => void setState(s.id, e.permission, 'unset')}>Не задано</button>
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
