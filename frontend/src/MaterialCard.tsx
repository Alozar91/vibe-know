// Карточка материала (US-037): поля, атрибуты (US-031, осиротевшие readonly —
// FR-051), теги, права пользователя (FR-129), правка с If-Match (FR-095),
// удаление (FR-090). Этап 5: кнопки переходов по матрице (US-015–021) и
// журнал статусов (FR-075). Этап 6: загрузка файла (US-007/008), состояние
// конвейера (US-011/012), скачивание (US-014), версии/diff/restore (US-041/042).
import { useEffect, useState } from 'react'
import { api, apiDownload, apiUpload, ApiError } from './auth'
import {
  PDF_RU, SCAN_RU, STATUS_RU, fmtDate,
  type FileState, type MaterialCard, type StatusLogEntry, type TransitionInfo,
  type VersionDiff, type VersionInfo,
} from './types'

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
  // Этап 6: файл/конвейер, версии
  const [fileState, setFileState] = useState<FileState | null>(null)
  const [versions, setVersions] = useState<VersionInfo[]>([])
  const [diff, setDiff] = useState<VersionDiff | null>(null)
  const [busy, setBusy] = useState(false)

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
      // Этап 6: состояние файла + версии (FR-058/145)
      const fs = await api<FileState>(`/materials/${materialId}/file-state`)
      setFileState(fs)
      const vs = await api<{ items: VersionInfo[] }>(`/materials/${materialId}/versions`)
      setVersions(vs.items)
      setDiff(null)
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

  // Этап 6: загрузка файла (§6.2); offer_text_update — диалог FR-030
  async function uploadFile(file: File) {
    if (!card) return
    setBusy(true)
    setError('')
    try {
      let r = await apiUpload<{
        file_state: FileState
        text_filled_automatically: boolean
        offer_text_update: boolean
        text_out_of_sync: boolean
      }>(`/materials/${card.id}/file`, file)
      if (r.offer_text_update) {
        const yes = window.confirm('Обновить текстовое представление содержимым файла?')
        r = await apiUpload<typeof r>(
          `/materials/${card.id}/file`, file,
          `?text_update_choice=${yes ? 'replace' : 'keep'}`,
        )
      }
      await load()
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    } finally {
      setBusy(false)
    }
  }

  // Этап 6: скачивание исходника/.md через api-стриминг (§6.4, FR-067/107)
  async function download(kind: 'file' | 'text.md' | 'pdf') {
    if (!card) return
    setError('')
    try {
      const r = await apiDownload(`/materials/${card.id}/${kind === 'file' ? 'file' : kind}`)
      if (!r.ok) {
        const p = await r.json().catch(() => ({}))
        throw new ApiError(r.status, (p as { code?: string }).code ?? 'HTTP_ERROR',
          (p as { title?: string }).title ?? 'Ошибка', (p as { detail?: string }).detail)
      }
      const blob = await r.blob()
      const cd = r.headers.get('content-disposition') ?? ''
      const m = /filename="([^"]+)"/.exec(cd)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = m?.[1] ?? (kind === 'pdf' ? 'preview.pdf' : kind)
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  // Этап 6: diff соседних версий (US-041 шаг 2)
  async function showDiff(n: number) {
    setError('')
    try {
      setDiff(await api<VersionDiff>(`/materials/${card!.id}/versions/${n}/diff`))
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  // Этап 6: восстановление версии (US-042, FR-148)
  async function restore(n: number) {
    if (!card || !window.confirm(`Восстановить версию ${n}? Текущее содержимое будет заменено (создаётся новая версия).`)) return
    setError('')
    try {
      await api(`/materials/${card.id}/versions/${n}/restore`, {
        method: 'POST',
        headers: { 'If-Match': String(card.version) },
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

      {/* Этап 6: файл, конвейер (US-011/012/013), скачивание (US-014) */}
      <h3>Файл</h3>
      {!fileState?.file_id && <p style={{ color: '#777' }}>Файл не загружен</p>}
      {fileState?.file_id && (
        <>
          <table style={{ borderCollapse: 'collapse', marginBottom: 8 }}>
            <tbody>
              <tr><td style={k}>Имя</td><td>{fileState.filename}</td></tr>
              <tr><td style={k}>Тип</td><td>{fileState.mime_type} · {Math.round((fileState.size_bytes ?? 0) / 1024)} КБ</td></tr>
              <tr><td style={k}>Антивирус</td><td>{fileState.scan_state && SCAN_RU[fileState.scan_state]}</td></tr>
              <tr><td style={k}>PDF</td><td>{fileState.pdf_state && PDF_RU[fileState.pdf_state]}</td></tr>
            </tbody>
          </table>
          <p>
            {fileState.scan_state === 'ready' && p.download && (
              <button onClick={() => download('file')}>Скачать файл</button>
            )}
            {fileState.scan_state !== 'ready' && (
              <small style={{ color: '#777' }}> Файл недоступен до завершения проверки (US-011)</small>
            )}
            {fileState.pdf_state === 'ready_pdf' && (
              <button onClick={() => download('pdf')} style={{ marginLeft: 8 }}>Скачать PDF (предпросмотр)</button>
            )}
            {p.download && card.text_content && (
              <button onClick={() => download('text.md')} style={{ marginLeft: 8 }}>Скачать текст .md</button>
            )}
          </p>
        </>
      )}
      {p.edit && card.status !== 'archived' && (
        <p>
          <input
            type="file" disabled={busy}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadFile(f); e.target.value = '' }}
          />
          {busy && <small> Загрузка…</small>}
        </p>
      )}
      {card.text_out_of_sync && (
        <p style={{ color: '#a60' }}>Текстовое представление не синхронизировано с файлом (FR-030)</p>
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

      {/* Этап 6: версии (US-041/042, FR-145–148) */}
      <h3>Версии</h3>
      {versions.length === 0 && <p style={{ color: '#777' }}>Версий ещё нет</p>}
      {versions.length > 0 && (
        <table style={{ borderCollapse: 'collapse', marginBottom: 8 }}>
          <thead>
            <tr>
              <th style={k}>№</th><th style={k}>Автор</th><th style={k}>Дата</th><th></th><th></th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.number}>
                <td style={k}>{v.number}</td>
                <td>{v.author_id.slice(0, 8)}…</td>
                <td>{fmtDate(v.created_at)}</td>
                <td style={{ paddingLeft: 8 }}>
                  <button onClick={() => showDiff(v.number)}>Сравнить с предыдущей</button>
                </td>
                <td style={{ paddingLeft: 8 }}>
                  {p.edit && card.status !== 'archived' && (
                    <button onClick={() => restore(v.number)}>Восстановить</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {diff && (
        <div style={{ background: '#f6f6f6', padding: 8, maxWidth: 720, overflowX: 'auto' }}>
          <h4>Сравнение версии {diff.number} с предыдущей</h4>
          {diff.file_changed && <p style={{ color: '#a60' }}>Файл изменён в этой версии</p>}
          {diff.metadata_changes.length > 0 && (
            <table style={{ borderCollapse: 'collapse' }}>
              <tbody>
                {diff.metadata_changes.map((c, i) => (
                  <tr key={i}>
                    <td style={k}>{c.field}</td>
                    <td style={{ color: '#b00', paddingRight: 12 }}>{c.old || '—'}</td>
                    <td style={{ color: '#070' }}>{c.new || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {diff.text_diff.length > 0 && (
            <pre style={{ fontSize: 12 }}>{diff.text_diff.join('\n')}</pre>
          )}
          {!diff.file_changed && diff.metadata_changes.length === 0 && diff.text_diff.length === 0 && (
            <p style={{ color: '#777' }}>Различий нет</p>
          )}
        </div>
      )}

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
