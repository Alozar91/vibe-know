// Карточка материала (US-037): поля, атрибуты (US-031, осиротевшие readonly —
// FR-051), теги, права пользователя (FR-129), правка с If-Match (FR-095),
// удаление (FR-090). Этап 5: кнопки переходов по матрице (US-015–021) и
// журнал статусов (FR-075). Этап 6: загрузка файла (US-007/008), состояние
// конвейера (US-011/012), скачивание (US-014), версии/diff/restore (US-041/042).
// modern-ui: двухпанельная карточка (содержание + боковая колонка действий).
import { useEffect, useState } from 'react'
import { api, apiDownload, apiUpload, ApiError } from './auth'
import {
  PDF_RU, SCAN_RU, STATUS_RU, fmtDate,
  type CommentInfo, type DictionaryInfo, type FileState, type GroupNode,
  type Material, type MaterialCard, type Page,
  type StatusLogEntry, type TransitionInfo, type VersionDiff, type VersionInfo,
} from './types'
import { Err, StatusBadge } from './ui'

interface AttrLite {
  id: string
  name: string
  dictionary_id?: string | null
}

interface Props {
  materialId: string
  onSaved: () => void
  onClosed: () => void
  onOpenCard?: (materialId: string) => void // этап 7: переход по ссылкам мастер/подчинённые (FR-126)
}

export default function MaterialCardView({ materialId, onSaved, onClosed, onOpenCard }: Props) {
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

  // ===== Этап 7: мастер-подчинённый, move/copy, комментарии =====

  // Дерево групп + справочники для диалогов (FR-109: выбор среди видимых групп)
  const [groups, setGroups] = useState<GroupNode[]>([])
  const [langOptions, setLangOptions] = useState<{ id: string; value: string }[]>([])
  const [comments, setComments] = useState<CommentInfo[]>([])
  const [commentText, setCommentText] = useState('')
  const [dialog, setDialog] = useState<null | 'child' | 'copy' | 'move' | 'master'>(null)
  const [childKind, setChildKind] = useState<'adaptation' | 'translation'>('adaptation')
  const [childLang, setChildLang] = useState('')
  const [childName, setChildName] = useState('')
  const [targetGroup, setTargetGroup] = useState('')
  const [masterName, setMasterName] = useState('')
  const [masterOptions, setMasterOptions] = useState<Material[]>([])

  useEffect(() => {
    if (card) {
      api<GroupNode[]>('/groups').then(setGroups).catch(() => setGroups([]))
      // Справочник атрибута «Язык» (FR-046): значения для диалога перевода
      Promise.all([
        api<DictionaryInfo[]>('/dictionaries').catch(() => []),
        api<{ items?: AttrLite[] } | AttrLite[]>('/attributes').catch(() => []),
      ]).then(([dicts, attrsRaw]) => {
        const attrs: AttrLite[] = Array.isArray(attrsRaw) ? attrsRaw : (attrsRaw.items ?? [])
        const lang = attrs.find((x) => x.name === 'Язык')
        const d = lang?.dictionary_id ? dicts.find((x) => x.id === lang.dictionary_id) : undefined
        setLangOptions(d?.value_items ?? [])
      })
    }
  }, [card?.id])

  useEffect(() => {
    api<{ items: CommentInfo[] }>(`/materials/${materialId}/comments`)
      .then((r) => setComments(r.items))
      .catch(() => setComments([]))
  }, [materialId, card?.version])

  function flatGroups(nodes: GroupNode[], depth = 0): { g: GroupNode; depth: number }[] {
    return nodes.flatMap((n) => [{ g: n, depth }, ...flatGroups(n.children ?? [], depth + 1)])
  }

  function openChildDialog() {
    if (!card) return
    setChildKind('adaptation')
    setChildLang('')
    setChildName(`${card.name} Адаптация`) // FR-035: имя по умолчанию
    setTargetGroup('')
    setDialog('child')
  }

  function openCopyDialog() {
    if (!card) return
    setChildName(`${card.name} Копия`) // FR-092
    setTargetGroup('')
    setDialog('copy')
  }

  function openMoveDialog() {
    if (!card) return
    setTargetGroup('')
    setDialog('move')
  }

  async function openMasterDialog() {
    if (!card) return
    setMasterName('')
    setMasterOptions([])
    setDialog('master')
  }

  // Поиск кандидатов в новые мастера (FR-036: approved/published, видимые)
  async function searchMasters(q: string) {
    setMasterName(q)
    if (q.trim().length < 2) { setMasterOptions([]); return }
    try {
      const r = await api<Page<Material>>(
        `/materials?sort=name&order=asc&per_page=10&status=approved`, // + published отдельно
      )
      const r2 = await api<Page<Material>>(`/materials?sort=name&order=asc&per_page=10&status=published`)
      const all = [...r.items, ...r2.items].filter(
        (m) => m.id !== card?.id && m.name.toLowerCase().includes(q.trim().toLowerCase()),
      )
      setMasterOptions(all)
    } catch {
      setMasterOptions([])
    }
  }

  async function createChild() {
    if (!card || !targetGroup) return
    setBusy(true)
    setError('')
    try {
      const body: Record<string, unknown> = {
        kind: childKind, group_id: targetGroup,
      }
      if (childName.trim() && childName.trim() !== defaultChildName()) body.name = childName.trim()
      if (childKind === 'translation') body.language_id = childLang
      await api(`/materials/${card.id}/children`, { method: 'POST', body: JSON.stringify(body) })
      setDialog(null)
      await load()
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    } finally {
      setBusy(false)
    }
  }

  function defaultChildName(): string {
    if (!card) return ''
    return childKind === 'translation' ? `${card.name} (Перевод, …)` : `${card.name} Адаптация`
  }

  async function doCopy() {
    if (!card || !targetGroup) return
    setBusy(true)
    setError('')
    try {
      await api(`/materials/${card.id}/copy`, {
        method: 'POST', body: JSON.stringify({ group_id: targetGroup, name: childName }),
      })
      setDialog(null)
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function doMove() {
    if (!card || !targetGroup) return
    setBusy(true)
    setError('')
    try {
      await api(`/materials/${card.id}/move`, {
        method: 'POST', body: JSON.stringify({ group_id: targetGroup }),
      })
      setDialog(null)
      await load()
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function changeMaster(newMasterId: string) {
    if (!card) return
    setBusy(true)
    setError('')
    try {
      await api(`/materials/${card.id}/master`, {
        method: 'POST', body: JSON.stringify({ master_id: newMasterId }),
      })
      setDialog(null)
      await load()
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function detachMaster() {
    if (!card || !window.confirm('Отвязать материал от мастера? Материал станет самостоятельным.')) return
    setError('')
    try {
      await api(`/materials/${card.id}/master`, { method: 'DELETE' })
      await load()
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e))
    }
  }

  async function addComment() {
    if (!card || !commentText.trim()) return
    setError('')
    try {
      await api(`/materials/${card.id}/comments`, {
        method: 'POST', body: JSON.stringify({ text: commentText }),
      })
      setCommentText('')
      const r = await api<{ items: CommentInfo[] }>(`/materials/${card.id}/comments`)
      setComments(r.items)
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

  if (error && !card) {
    return (
      <div>
        <Err>{error}</Err>
        <button className="btn ghost" onClick={onClosed}>← К списку</button>
      </div>
    )
  }
  if (!card) return <div className="spin">Загрузка…</div>

  const p = card.permissions ?? {}

  return (
    <div>
      <div className="btnrow">
        <button className="btn ghost small" onClick={onClosed}>← К списку</button>
      </div>

      <div className="panel">
        <div className="cardhead">
          <StatusBadge status={card.status} />
          <h2>{card.name}</h2>
          <div className="sub">{STATUS_RU[card.status]} · версия {card.version}</div>
        </div>
        <Err>{error}</Err>

        <div className="cardgrid">
          <div className="cmain">
            <table className="kv">
              <tbody>
                <tr><td className="k">Тип</td><td>{card.type_name ?? card.type_id}</td></tr>
                <tr><td className="k">Автор</td><td className="mono">{card.author_id.slice(0, 8)}…</td></tr>
                <tr><td className="k">Изменён</td><td>{fmtDate(card.updated_at)}</td></tr>
                <tr><td className="k">Опубликован</td><td>{fmtDate(card.published_at)}</td></tr>
              </tbody>
            </table>

            {/* Этап 7 (FR-126): ссылка на мастера или список подчинённых */}
            <div className="fld">
              <label>Мастер / подчинённые</label>
              {card.master_id ? (
                <div>
                  Мастер:{' '}
                  {card.master ? (
                    <a href="#" onClick={(e) => { e.preventDefault(); onOpenCard?.(card.master!.id) }}>
                      {card.master.name}
                    </a>
                  ) : card.master_id}{' '}
                  <small className="note">({STATUS_RU[card.master?.status ?? card.status]})</small>
                  {p.edit && card.status !== 'archived' && (
                    <button className="btn small" onClick={detachMaster} style={{ marginLeft: 12 }}>Отвязать от мастера</button>
                  )}
                </div>
              ) : (
                <span className="note">Самостоятельный материал (мастера нет)</span>
              )}
              {card.children.length > 0 && (
                <ul className="children-list">
                  {card.children.map((ch) => (
                    <li key={ch.id}>
                      <a href="#" onClick={(e) => { e.preventDefault(); onOpenCard?.(ch.id) }}>{ch.name}</a>{' '}
                      <small className="note">{STATUS_RU[ch.status]}</small>
                    </li>
                  ))}
                </ul>
              )}
              {card.children.length === 0 && !card.master_id && (
                <span className="note">Подчинённых нет</span>
              )}
            </div>

            {p.edit ? (
              editing ? (
                <div>
                  <label className="field">
                    <span className="lbl">Название</span>
                    <input value={name} onChange={(e) => setName(e.target.value)} />
                  </label>
                  <label className="field">
                    <span className="lbl">Текст (Markdown)</span>
                    <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} />
                  </label>
                  <div className="btnrow">
                    <button className="btn primary" onClick={save} disabled={saving}>{saving ? 'Сохранение…' : 'Сохранить'}</button>
                    <button className="btn ghost" onClick={() => { setEditing(false); setName(card.name); setText(card.text_content ?? '') }}>
                      Отмена
                    </button>
                  </div>
                </div>
              ) : (
                <div className="btnrow">
                  <button className="btn primary" onClick={() => setEditing(true)}>Редактировать</button>
                  {p.delete && (card.status === 'draft' || card.status === 'in_review') && (
                    <button className="btn danger" onClick={remove}>Удалить</button>
                  )}
                </div>
              )
            ) : (
              <p className="note">Редактирование недоступно (нет права «Редактирование»)</p>
            )}

            {/* Содержание */}
            {!editing && card.text_content && (
              <div className="fld">
                <label>Содержание</label>
                <div className="content-text">{card.text_content}</div>
              </div>
            )}

            {/* Атрибуты */}
            <div className="fld">
              <label>Атрибуты</label>
              {card.attributes.length === 0 ? (
                <span className="note">Не заполнены</span>
              ) : (
                <table className="kv">
                  <tbody>
                    {card.attributes.map((a) => (
                      <tr key={a.attribute_id}>
                        <td className="k">
                          {a.name}
                          {a.is_required && <span className="req"> *</span>}
                          {a.readonly && <small className="note"> (только чтение)</small>}
                        </td>
                        <td>{a.values.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Этап 7: комментарии (US-038, FR-096–098) */}
            <div className="fld">
              <label>Комментарии</label>
              {comments.length === 0 && <span className="note">Комментариев нет</span>}
              <ul className="comment-list">
                {comments.map((c) => (
                  <li key={c.id}>
                    <small className="mono">{fmtDate(c.created_at)}</small>
                    <span className="mono">{c.author_id.slice(0, 8)}…</span>
                    <span style={{ whiteSpace: 'pre-wrap' }}>{c.text}</span>
                  </li>
                ))}
              </ul>
              {/* FR-098: добавляют участники процесса (автор + edit/review/publish);
                  право create в карте — не участника; проверка — на сервере */}
              {(p.edit || p.review || p.publish || card.status === 'draft') && (
                <div className="btnrow">
                  <textarea
                    value={commentText} onChange={(e) => setCommentText(e.target.value)}
                    placeholder="Добавить комментарий…" rows={2} style={{ flex: 1, minWidth: 240 }}
                  />
                  <button className="btn small" onClick={addComment} disabled={!commentText.trim()}>Отправить</button>
                </div>
              )}
            </div>
          </div>

          {/* ============ Боковая колонка: действия, файл, версии ============ */}
          <div className="cside">
            {/* Этап 5: действия жизненного цикла по матрице (US-015–021) */}
            <div className="fld">
              <label>Действия жизненного цикла</label>
              {transitions.length === 0 && (
                <span className="note">Нет доступных переходов из статуса «{STATUS_RU[card.status]}»</span>
              )}
              <div className="btnrow">
                {transitions.map((t) => (
                  <button
                    key={t.id}
                    className={`btn small ${t.allowed ? 'primary' : 'ghost'}`}
                    onClick={() => doTransition(t)}
                    disabled={!t.allowed}
                    title={t.allowed ? 'Права перехода: ' + t.permissions.map((x) => RUS[x] ?? x).join(', ') : 'Нет права на этот переход'}
                  >
                    → {STATUS_RU[t.to_status]}
                  </button>
                ))}
              </div>
            </div>

            {/* Действия этапа 7 */}
            <div className="fld">
              <label>Связи и копирование</label>
              <div className="btnrow">
                {p.create && <button className="btn small" onClick={openChildDialog}>Подчинённый</button>}
                {p.copy && <button className="btn small" onClick={openCopyDialog}>Копировать</button>}
                {p.move && card.children.length === 0 && card.status !== 'archived' && (
                  <button className="btn small" onClick={openMoveDialog}>Переместить</button>
                )}
                {p.edit && card.master_id && card.status !== 'archived' && (
                  <button className="btn small" onClick={openMasterDialog}>Сменить мастера</button>
                )}
              </div>
            </div>

            {/* Этап 6: файл, конвейер (US-011/012/013), скачивание (US-014) */}
            <div className="fld">
              <label>Файл</label>
              {!fileState?.file_id && <span className="note">Файл не загружен</span>}
              {fileState?.file_id && (
                <>
                  <table className="kv">
                    <tbody>
                      <tr><td className="k">Имя</td><td>{fileState.filename}</td></tr>
                      <tr><td className="k">Тип</td><td>{fileState.mime_type} · {Math.round((fileState.size_bytes ?? 0) / 1024)} КБ</td></tr>
                      <tr><td className="k">Антивирус</td><td>{fileState.scan_state && SCAN_RU[fileState.scan_state]}</td></tr>
                      <tr><td className="k">PDF</td><td>{fileState.pdf_state && PDF_RU[fileState.pdf_state]}</td></tr>
                    </tbody>
                  </table>
                  <div className="btnrow">
                    {fileState.scan_state === 'ready' && p.download && (
                      <button className="btn small" onClick={() => download('file')}>Скачать файл</button>
                    )}
                    {fileState.pdf_state === 'ready_pdf' && (
                      <button className="btn small" onClick={() => download('pdf')}>PDF</button>
                    )}
                    {p.download && card.text_content && (
                      <button className="btn small" onClick={() => download('text.md')}>Текст .md</button>
                    )}
                  </div>
                  {fileState.scan_state !== 'ready' && (
                    <div className="alert warn">Файл недоступен до завершения проверки (US-011)</div>
                  )}
                </>
              )}
              {p.edit && card.status !== 'archived' && (
                <div className="btnrow">
                  <input
                    type="file" disabled={busy}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadFile(f); e.target.value = '' }}
                  />
                  {busy && <small className="note"> Загрузка…</small>}
                </div>
              )}
              {card.text_out_of_sync && (
                <div className="alert warn">Текстовое представление не синхронизировано с файлом (FR-030)</div>
              )}
            </div>

            {/* Этап 6: версии (US-041/042, FR-145–148) */}
            <div className="fld">
              <label>Версии</label>
              {versions.length === 0 && <span className="note">Версий ещё нет</span>}
              <ul className="version-list">
                {versions.map((v) => (
                  <li key={v.number}>
                    <span className="mono">v{v.number}</span>
                    <span className="mono">{fmtDate(v.created_at)}</span>
                    <button className="btn small" onClick={() => showDiff(v.number)}>diff</button>
                    {p.edit && card.status !== 'archived' && (
                      <button className="btn small" onClick={() => restore(v.number)}>Восстановить</button>
                    )}
                  </li>
                ))}
              </ul>
              {diff && (
                <div className="diffbox">
                  <b>Сравнение версии {diff.number} с предыдущей</b>
                  {diff.file_changed && <div className="alert warn">Файл изменён в этой версии</div>}
                  {diff.metadata_changes.length > 0 && (
                    <table className="kv">
                      <tbody>
                        {diff.metadata_changes.map((c, i) => (
                          <tr key={i}>
                            <td className="k">{c.field}</td>
                            <td className="old" style={{ paddingRight: 12 }}>{c.old || '—'}</td>
                            <td className="new">{c.new || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {diff.text_diff.length > 0 && <pre>{diff.text_diff.join('\n')}</pre>}
                  {!diff.file_changed && diff.metadata_changes.length === 0 && diff.text_diff.length === 0 && (
                    <div className="note">Различий нет</div>
                  )}
                </div>
              )}
            </div>

            {/* Этап 5: журнал статусов (FR-075) */}
            <div className="fld">
              <label>История статусов</label>
              {log.length === 0 && <span className="note">Переходов ещё не было</span>}
              <ul className="pipeline">
                {log.map((e, i) => (
                  <li key={i}>
                    <span className="when">{fmtDate(e.created_at)}</span>
                    <span>
                      {e.from_status ? `${STATUS_RU[e.from_status]} → ` : ''}
                      {STATUS_RU[e.to_status]}
                    </span>
                    <span className="note">{e.user_display_name}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Права пользователя (FR-129) */}
            <div className="fld">
              <label>Права (ваш доступ)</label>
              <span className="note">
                {Object.entries(p).filter(([, v]) => v).map(([k2]) => RUS[k2] ?? k2).join(', ') || 'только просмотр'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Диалог этапа 7: создание подчинённого (US-024/025) */}
      {dialog === 'child' && (
        <div className="dialog">
          <h4>Создать подчинённый материал</h4>
          <label className="field">
            <span className="lbl">Вид</span>
            <select value={childKind} onChange={(e) => {
              const kind = e.target.value as 'adaptation' | 'translation'
              setChildKind(kind)
              setChildName(kind === 'translation' ? `${card!.name} (Перевод, …)` : `${card!.name} Адаптация`)
            }}>
              <option value="adaptation">Адаптация</option>
              <option value="translation">Перевод</option>
            </select>
          </label>
          {childKind === 'translation' && (
            <label className="field">
              <span className="lbl">Язык перевода (обязателен — US-025 A1)</span>
              <select value={childLang} onChange={(e) => setChildLang(e.target.value)}>
                <option value="">— выберите язык —</option>
                {langOptions.map((v) => (
                  <option key={v.id} value={v.id}>{v.value}</option>
                ))}
              </select>
              {langOptions.length === 0 && <div className="alert err"> Справочник «Язык» не заведён (СА: атрибуты → справочники)</div>}
            </label>
          )}
          <label className="field">
            <span className="lbl">Имя (по умолчанию — FR-035)</span>
            <input value={childName} onChange={(e) => setChildName(e.target.value)} />
          </label>
          <label className="field">
            <span className="lbl">Целевая группа</span>
            <select value={targetGroup} onChange={(e) => setTargetGroup(e.target.value)}>
              <option value="">— выберите группу —</option>
              {flatGroups(groups).map(({ g, depth }) => (
                <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
              ))}
            </select>
          </label>
          <div className="btnrow">
            <button className="btn primary" onClick={createChild} disabled={busy || !targetGroup || (childKind === 'translation' && !childLang.trim())}>
              Создать
            </button>
            <button className="btn ghost" onClick={() => setDialog(null)}>Отмена</button>
          </div>
        </div>
      )}

      {/* Диалог: копирование (US-028) */}
      {dialog === 'copy' && (
        <div className="dialog">
          <h4>Копировать материал</h4>
          <p className="note">Имя копии: {childName} (счётчик при конфликте — FR-092)</p>
          <label className="field">
            <span className="lbl">Целевая группа</span>
            <select value={targetGroup} onChange={(e) => setTargetGroup(e.target.value)}>
              <option value="">— выберите группу —</option>
              {flatGroups(groups).map(({ g, depth }) => (
                <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
              ))}
            </select>
          </label>
          <div className="btnrow">
            <button className="btn primary" onClick={doCopy} disabled={busy || !targetGroup}>Копировать</button>
            <button className="btn ghost" onClick={() => setDialog(null)}>Отмена</button>
          </div>
        </div>
      )}

      {/* Диалог: перемещение (US-027) */}
      {dialog === 'move' && (
        <div className="dialog">
          <h4>Переместить материал</h4>
          <p className="note">
            Требуется право «Перемещение» в обеих группах. При конфликте имени операция будет
            отклонена — переименуйте материал заранее (FR-037).
          </p>
          <label className="field">
            <span className="lbl">Целевая группа</span>
            <select value={targetGroup} onChange={(e) => setTargetGroup(e.target.value)}>
              <option value="">— выберите группу —</option>
              {flatGroups(groups).map(({ g, depth }) => (
                <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
              ))}
            </select>
          </label>
          <div className="btnrow">
            <button className="btn primary" onClick={doMove} disabled={busy || !targetGroup}>Переместить</button>
            <button className="btn ghost" onClick={() => setDialog(null)}>Отмена</button>
          </div>
        </div>
      )}

      {/* Диалог: смена мастера (US-026) */}
      {dialog === 'master' && (
        <div className="dialog">
          <h4>Сменить мастера</h4>
          <label className="field">
            <span className="lbl">Новый мастер (approved/published, FR-036)</span>
            <input value={masterName} onChange={(e) => searchMasters(e.target.value)} placeholder="Начните вводить название" />
          </label>
          <ul className="master-options">
            {masterOptions.map((m) => (
              <li key={m.id}>
                <button className="btn small" onClick={() => changeMaster(m.id)} disabled={busy}>{m.name}</button>
                <small className="note"> {STATUS_RU[m.status]}</small>
              </li>
            ))}
          </ul>
          <button className="btn ghost" onClick={() => setDialog(null)}>Отмена</button>
        </div>
      )}
    </div>
  )
}

const RUS: Record<string, string> = {
  view: 'Просмотр', create: 'Создание', edit: 'Редактирование', delete: 'Удаление',
  review: 'Ревью', publish: 'Публикация', archive: 'Архивация', copy: 'Копирование',
  move: 'Перемещение', download: 'Скачивание', manage_permissions: 'Управление правами',
}
