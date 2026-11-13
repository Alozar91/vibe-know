// Матрица переходов (US-046, СА): checkbox-подобный обзор + права переходов
// (несколько — достаточно любого, FR-070), удаление незащищённых (FR-073),
// создание правила. is_protected — только чтение.
// Реорганизация frontend: вызовы — через src/api/admin.
import { useEffect, useState } from 'react'
import {
  createTransitionRule, deleteTransitionRule, getTransitionRules, updateTransitionRule,
  type TransitionRule,
} from '../../../api/admin'
import { PERMISSIONS_RU, STATUS_RU, errText } from '../../../shared/lib/dicts'
import { Err, Ok } from '../../../shared/ui/index'

const PERMISSIONS = [
  'edit', 'review', 'publish', 'archive', 'view',
  'create', 'delete', 'copy', 'move', 'download', 'manage_permissions',
] as const

const STATUSES = Object.keys(STATUS_RU) as (keyof typeof STATUS_RU)[]

export default function TransitionMatrix() {
  const [rules, setRules] = useState<TransitionRule[]>([])
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [newFrom, setNewFrom] = useState('')
  const [newTo, setNewTo] = useState('')
  const [newPerms, setNewPerms] = useState<string[]>([])

  async function load() {
    setError('')
    try {
      setRules(await getTransitionRules())
    } catch (e) {
      setError(errText(e))
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function savePerms(rule: TransitionRule, perm: string) {
    setError('')
    setMsg('')
    const perms = rule.permissions.includes(perm)
      ? rule.permissions.filter((x) => x !== perm) // снять галочку
      : [...rule.permissions, perm] // поставить
    try {
      const updated = await updateTransitionRule(rule.id, perms)
      setRules((rs) => rs.map((r) => (r.id === updated.id ? updated : r)))
    } catch (e) {
      setError(errText(e))
    }
  }

  async function removeRule(rule: TransitionRule) {
    if (!window.confirm(`Удалить переход ${rule.from_status ? STATUS_RU[rule.from_status] : '*'} → ${STATUS_RU[rule.to_status]}?`)) return
    setError('')
    setMsg('')
    try {
      await deleteTransitionRule(rule.id)
      setMsg('Правило удалено; существующие материалы остаются в текущих статусах (FR-074)')
      await load()
    } catch (e) {
      setError(errText(e))
    }
  }

  async function createRule() {
    setError('')
    setMsg('')
    if (!newTo) {
      setError('Выберите целевой статус')
      return
    }
    try {
      await createTransitionRule({
        from_status: newFrom || null, // пусто = «*» (любой, кроме архива)
        to_status: newTo,
        permissions: newPerms,
      })
      setMsg('Правило добавлено')
      setNewFrom('')
      setNewTo('')
      setNewPerms([])
      await load()
    } catch (e) {
      setError(errText(e))
    }
  }

  function toggleNewPerm(p: string) {
    setNewPerms((ps) => (ps.includes(p) ? ps.filter((x) => x !== p) : [...ps, p]))
  }

  return (
    <div>
      <div className="pagehead"><h2>Матрица переходов</h2></div>
      <p className="note">
        Право проверяется на материале с учётом наследования от групп; достаточно любого из
        назначенных (FR-070). Переход без прав недоступен никому, кроме СА (FR-072).
        Защищённые переходы (в «Публикация» — только из «Утверждён»; в «Архив» — из любого
        статуса) нельзя удалить (FR-073).
      </p>
      <Err>{error}</Err>
      <Ok>{msg}</Ok>

      <div className="panel">
        <table className="tbl">
          <thead>
            <tr>
              <th>Из статуса</th>
              <th>В статус</th>
              <th>Права перехода</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{r.from_status ? STATUS_RU[r.from_status] : '* (любой)'}</td>
                <td className="nowrap">{STATUS_RU[r.to_status]}</td>
                <td>
                  {PERMISSIONS.map((p) => (
                    <label key={p} className="checkrow">
                      <input
                        type="checkbox"
                        checked={r.permissions.includes(p)}
                        onChange={() => savePerms(r, p)}
                      />
                      {PERMISSIONS_RU[p]}
                    </label>
                  ))}
                </td>
                <td>
                  {r.is_protected ? (
                    <small className="note">защищён</small>
                  ) : (
                    <button className="btn danger small" onClick={() => removeRule(r)}>Удалить</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Добавить правило</h3>
      <div className="panel">
        <div className="panel-body">
          <div className="btnrow">
            <label className="srchfld">Из статуса:
              <select value={newFrom} onChange={(e) => setNewFrom(e.target.value)}>
                <option value="">* (любой, кроме «Архива»)</option>
                {STATUSES.map((s) => <option key={s} value={s}>{STATUS_RU[s]}</option>)}
              </select>
            </label>
            <label className="srchfld">В статус:
              <select value={newTo} onChange={(e) => setNewTo(e.target.value)}>
                <option value="">— выберите —</option>
                {STATUSES.map((s) => <option key={s} value={s}>{STATUS_RU[s]}</option>)}
              </select>
            </label>
          </div>
          <div style={{ marginBottom: 8 }}>
            {PERMISSIONS.map((p) => (
              <label key={p} className="checkrow">
                <input type="checkbox" checked={newPerms.includes(p)} onChange={() => toggleNewPerm(p)} />
                {PERMISSIONS_RU[p]}
              </label>
            ))}
          </div>
          <button className="btn primary" onClick={createRule}>Добавить</button>
        </div>
      </div>
    </div>
  )
}
