// Матрица переходов (US-046, СА): checkbox-подобный обзор + права переходов
// (несколько — достаточно любого, FR-070), удаление незащищённых (FR-073),
// создание правила. is_protected — только чтение.
import { useEffect, useState } from 'react'
import { api, ApiError } from './auth'
import { STATUS_RU, type Material } from './types'

type Rule = {
  id: string
  from_status: Material['status'] | null
  to_status: Material['status']
  is_protected: boolean
  permissions: string[]
}

const PERMISSIONS = [
  'edit', 'review', 'publish', 'archive', 'view',
  'create', 'delete', 'copy', 'move', 'download', 'manage_permissions',
] as const

const PERM_RU: Record<string, string> = {
  view: 'Просмотр', create: 'Создание', edit: 'Редактирование', delete: 'Удаление',
  review: 'Ревью (утверждение)', publish: 'Публикация', archive: 'Архивация',
  copy: 'Копирование', move: 'Перемещение', download: 'Скачивание',
  manage_permissions: 'Управление правами',
}

const STATUSES = Object.keys(STATUS_RU) as Material['status'][]

export default function TransitionMatrix() {
  const [rules, setRules] = useState<Rule[]>([])
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [newFrom, setNewFrom] = useState('')
  const [newTo, setNewTo] = useState('')
  const [newPerms, setNewPerms] = useState<string[]>([])

  async function load() {
    setError('')
    try {
      setRules(await api<Rule[]>('/transition-rules'))
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function savePerms(rule: Rule, perm: string) {
    setError('')
    setMsg('')
    const perms = rule.permissions.includes(perm)
      ? rule.permissions.filter((x) => x !== perm) // снять галочку
      : [...rule.permissions, perm] // поставить
    try {
      const updated = await api<Rule>(`/transition-rules/${rule.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ permissions: perms }),
      })
      setRules((rs) => rs.map((r) => (r.id === updated.id ? updated : r)))
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  async function removeRule(rule: Rule) {
    if (!window.confirm(`Удалить переход ${rule.from_status ? STATUS_RU[rule.from_status] : '*'} → ${STATUS_RU[rule.to_status]}?`)) return
    setError('')
    setMsg('')
    try {
      await api(`/transition-rules/${rule.id}`, { method: 'DELETE' })
      setMsg('Правило удалено; существующие материалы остаются в текущих статусах (FR-074)')
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
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
      await api('/transition-rules', {
        method: 'POST',
        body: JSON.stringify({
          from_status: newFrom || null, // пусто = «*» (любой, кроме архива)
          to_status: newTo,
          permissions: newPerms,
        }),
      })
      setMsg('Правило добавлено')
      setNewFrom('')
      setNewTo('')
      setNewPerms([])
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  function toggleNewPerm(p: string) {
    setNewPerms((ps) => (ps.includes(p) ? ps.filter((x) => x !== p) : [...ps, p]))
  }

  return (
    <div>
      <h2>Матрица переходов</h2>
      <p style={{ color: '#777' }}>
        Право проверяется на материале с учётом наследования от групп; достаточно любого из
        назначенных (FR-070). Переход без прав недоступен никому, кроме СА (FR-072).
        Защищённые переходы (в «Публикация» — только из «Утверждён»; в «Архив» — из любого
        статуса) нельзя удалить (FR-073).
      </p>
      {error && <p style={{ color: '#b00' }}>{error}</p>}
      {msg && <p style={{ color: '#060' }}>{msg}</p>}

      <table style={{ borderCollapse: 'collapse', marginBottom: 20 }}>
        <thead>
          <tr>
            <th style={th}>Из статуса</th>
            <th style={th}>В статус</th>
            <th style={th}>Права перехода</th>
            <th style={th}></th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.id}>
              <td style={td}>{r.from_status ? STATUS_RU[r.from_status] : '* (любой)'}</td>
              <td style={td}>{STATUS_RU[r.to_status]}</td>
              <td style={td}>
                {PERMISSIONS.map((p) => (
                  <label key={p} style={{ marginRight: 10, whiteSpace: 'nowrap' }}>
                    <input
                      type="checkbox"
                      checked={r.permissions.includes(p)}
                      onChange={() => savePerms(r, p)}
                    />{' '}
                    {PERM_RU[p]}
                  </label>
                ))}
              </td>
              <td style={td}>
                {r.is_protected ? (
                  <small style={{ color: '#777' }}>защищён</small>
                ) : (
                  <button onClick={() => removeRule(r)} style={{ color: '#b00' }}>Удалить</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Добавить правило</h3>
      <div style={{ marginBottom: 8 }}>
        <label>Из статуса:{' '}
          <select value={newFrom} onChange={(e) => setNewFrom(e.target.value)}>
            <option value="">* (любой, кроме «Архива»)</option>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_RU[s]}</option>)}
          </select>
        </label>{' '}
        <label>В статус:{' '}
          <select value={newTo} onChange={(e) => setNewTo(e.target.value)}>
            <option value="">— выберите —</option>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_RU[s]}</option>)}
          </select>
        </label>
      </div>
      <div style={{ marginBottom: 8 }}>
        {PERMISSIONS.map((p) => (
          <label key={p} style={{ marginRight: 10, whiteSpace: 'nowrap' }}>
            <input type="checkbox" checked={newPerms.includes(p)} onChange={() => toggleNewPerm(p)} />{' '}
            {PERM_RU[p]}
          </label>
        ))}
      </div>
      <button onClick={createRule}>Добавить</button>
    </div>
  )
}

const th: React.CSSProperties = { textAlign: 'left', borderBottom: '2px solid #333', padding: '4px 10px' }
const td: React.CSSProperties = { borderBottom: '1px solid #ddd', padding: '6px 10px', verticalAlign: 'top' }
