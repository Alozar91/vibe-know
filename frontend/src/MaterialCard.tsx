// Карточка материала (US-037): поля, атрибуты (US-031, осиротевшие readonly —
// FR-051), теги, права пользователя (FR-129), правка с If-Match (FR-095),
// удаление (FR-090). Этап 5: кнопки переходов по матрице (US-015–021) и
// журнал статусов (FR-075). Файлы — этап 6.
import { useEffect, useState } from 'react'
import { api, ApiError } from './auth'
import { STATUS_RU, fmtDate, type MaterialCard, type StatusLogEntry, type TransitionInfo } from './types'

interface Props {
  materialId: string
  onSaved: () => void
  onClosed: () => void
}

export default function MaterialCardView({ materialId, onSaved, onClosed }: Props) {
  const [card, setCard] = useState<MaterialCard | null>(null)
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [transitions, setTransitions] = useState<TransitionInfo[]>([])
  const [log, setLog] = useState<StatusLogEntry[]>([])

  async function load() {
    setError('')
    try {
      const c = await api<MaterialCard>(`/materials/${materialId}`)
      setCard(c)
      setName(c.name)
      setText(c.text_content ?? '')
      // Этап 5: доступные переходы + журнал статусов (FR-070/075)
      const tr = await api<TransitionInfo[]>(`/materials/${materialId}/transitions`)
      setTransitions(tr)
      const sl = await api<StatusLogEntry[]>(`/materials/${materialId}/status-log`)
      setLog(sl)
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [materialId])

  async function save() {
    if (!card) return
    setSaving(true)
    setError('')
    try {
      await api(`/materials/${card.id}`, {
        method: 'PATCH',
        headers: { 'If-Match': String(card.version) },
        body: JSON.stringify({ name, text_content: text }),
      })
      setEditing(false)
      await load()
      onSaved()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'VERSION_CONFLICT') {
        setError('Материал изменён другим пользователем. Обновите карточку и повторите.')
        await load()
      } else {
        setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
      }
    } finally {
      setSaving(false)
    }
  }

  async function remove() {
    if (!card || !window.confirm(`Удалить «${card.name}»?`)) return
    setError('')
    try {
      await api(`/materials/${card.id}`, {
        method: 'DELETE',
        headers: { 'If-Match': String(card.version) },
      })
      onSaved()
      onClosed()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  // Этап 5: переход статуса (§4.1) — If-Match обязателен (FR-094/095)
  async function doTransition(t: TransitionInfo) {
    if (!card) return
    const target = STATUS_RU[t.to_status]
    let confirmCascade = false
    if (t.need_cascade) {
      const msg = `Вместе с мастером будет заархивировано ещё ${t.children_count} подчинённых материалов. Продолжить?`
      if (!window.confirm(msg)) return // FR-039: подтверждение каскада
      confirmCascade = true
    }
    if (!window.confirm(`Перевести «${card.name}»: ${STATUS_RU[card.status]} → ${target}?`)) return
    setError('')
    try {
      await api(`/materials/${card.id}/transitions`, {
        method: 'POST',
        headers: { 'If-Match': String(card.version) },
        body: JSON.stringify({ to_status: t.to_status, confirm_cascade: confirmCascade }),
      })
      await load()
      onSaved()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'VERSION_CONFLICT') {
        setError('Материал изменён другим пользователем. Обновите карточку и повторите.')
        await load()
      } else {
        setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
      }
    }
  }

  if (error && !card) return <div><p style={{ color: '#b00' }}>{error}</p><button onClick={onClosed}>Закрыть</button></div>
  if (!card) return <p>Загрузка…</p>

  const p = card.permissions ?? {}

  return (
    <div>
      <button onClick={onClosed}>← К списку</button>
      <h2>
        {card.name}{' '}
        <small style={{ color: '#777' }}>{STATUS_RU[card.status]} · версия {card.version}</small>
      </h2>
      {error && <p style={{ color: '#b00' }}>{error}</p>}

      <table style={{ borderCollapse: 'collapse', marginBottom: 16 }}>
        <tbody>
          <tr><td style={k}>Тип</td><td>{card.type_name ?? card.type_id}</td></tr>
          <tr><td style={k}>Автор</td><td>{card.author_id.slice(0, 8)}…</td></tr>
          <tr><td style={k}>Изменён</td><td>{fmtDate(card.updated_at)}</td></tr>
          <tr><td style={k}>Опубликован</td><td>{fmtDate(card.published_at)}</td></tr>
        </tbody>
      </table>

      {p.edit ? (
        editing ? (
          <div style={{ maxWidth: 640 }}>
            <label>Название<br />
              <input value={name} onChange={(e) => setName(e.target.value)} style={{ width: '100%' }} />
            </label><br /><br />
            <label>Текст (Markdown)<br />
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} style={{ width: '100%' }} />
            </label><br />
            <button onClick={save} disabled={saving}>{saving ? 'Сохранение…' : 'Сохранить'}</button>{' '}
            <button onClick={() => { setEditing(false); setName(card.name); setText(card.text_content ?? '') }}>
              Отмена
            </button>
          </div>
        ) : (
          <p>
            <button onClick={() => setEditing(true)}>Редактировать</button>{' '}
            {p.delete && (card.status === 'draft' || card.status === 'in_review') &&
              <button onClick={remove} style={{ color: '#b00' }}>Удалить</button>}
          </p>
        )
      ) : (
        <p style={{ color: '#777' }}>Редактирование недоступно (нет права «Редактирование»)</p>
      )}

      {/* Этап 5: действия жизненного цикла по матрице (US-015–021) */}
      <h3>Действия</h3>
      {transitions.length === 0 && <p style={{ color: '#777' }}>Нет доступных переходов из статуса «{STATUS_RU[card.status]}»</p>}
      <p>
        {transitions.map((t) => (
          <span key={t.id} style={{ marginRight: 8 }}>
            <button
              onClick={() => doTransition(t)}
              disabled={!t.allowed}
              title={t.allowed ? 'Права перехода: ' + t.permissions.map((x) => RUS[x] ?? x).join(', ') : 'Нет права на этот переход'}
            >
              → {STATUS_RU[t.to_status]}
            </button>
          </span>
        ))}
      </p>

      {/* Этап 5: журнал статусов (FR-075) */}
      <h3>История статусов</h3>
      {log.length === 0 && <p style={{ color: '#777' }}>Переходов ещё не было</p>}
      <table style={{ borderCollapse: 'collapse' }}>
        <tbody>
          {log.map((e, i) => (
            <tr key={i}>
              <td style={k}>{fmtDate(e.created_at)}</td>
              <td>
                {e.from_status ? `${STATUS_RU[e.from_status]} → ` : ''}
                {STATUS_RU[e.to_status]}
              </td>
              <td style={{ paddingLeft: 12 }}>{e.user_display_name}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Атрибуты</h3>
      {card.attributes.length === 0 && <p style={{ color: '#777' }}>Не заполнены</p>}
      <table style={{ borderCollapse: 'collapse' }}>
        <tbody>
          {card.attributes.map((a) => (
            <tr key={a.attribute_id}>
              <td style={k}>
                {a.name}
                {a.is_required && <span style={{ color: '#b00' }}> *</span>}
                {a.readonly && <small style={{ color: '#777' }}> (только чтение)</small>}
              </td>
              <td>{a.values.join(', ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Права (ваш доступ)</h3>
      <p style={{ color: '#777' }}>
        {Object.entries(p).filter(([, v]) => v).map(([k2]) => RUS[k2] ?? k2).join(', ') || 'только просмотр'}
      </p>
    </div>
  )
}

const k: React.CSSProperties = { color: '#666', paddingRight: 16, verticalAlign: 'top', whiteSpace: 'nowrap' }

const RUS: Record<string, string> = {
  view: 'Просмотр', create: 'Создание', edit: 'Редактирование', delete: 'Удаление',
  review: 'Ревью', publish: 'Публикация', archive: 'Архивация', copy: 'Копирование',
  move: 'Перемещение', download: 'Скачивание', manage_permissions: 'Управление правами',
}
