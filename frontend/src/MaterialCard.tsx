// Карточка материала (US-037): поля, атрибуты (US-031, осиротевшие readonly —
// FR-051), теги, права пользователя (FR-129), правка с If-Match (FR-095),
// удаление (FR-090). Этап 5: кнопки переходов по матрице (US-015–021) и
// журнал статусов (FR-075). Этап 6: загрузка файла (US-007/008), состояние
// конвейера (US-011/012), скачивание (US-014), версии/diff/restore (US-041/042).
import { useEffect, useState } from 'react'
import { api, apiDownload, apiUpload, ApiError } from './auth'
import {
  PDF_RU, SCAN_RU, STATUS_RU, fmtDate,
  type CommentInfo, type DictionaryInfo, type FileState, type GroupNode,
  type Material, type MaterialCard, type Page,
  type StatusLogEntry, type TransitionInfo, type VersionDiff, type VersionInfo,
} from './types'

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
        method: 'POST', body: JSON.stringify({ group_id: targetGroup }),
      })
      setDialog(null)
      onSaved()
      // копия в другой группе — остаёмся в карточке исходника
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

      {/* Этап 7 (FR-126): ссылка на мастера или список подчинённых */}
      <h3>Мастер / подчинённые</h3>
      {card.master_id ? (
        <p>
          Мастер:{' '}
          {card.master ? (
            <a href="#" onClick={(e) => { e.preventDefault(); onOpenCard?.(card.master!.id) }}>
              {card.master.name}
            </a>
          ) : card.master_id}{' '}
          <small style={{ color: '#777' }}>({STATUS_RU[card.master?.status ?? card.status]})</small>
          {p.edit && card.status !== 'archived' && (
            <button onClick={detachMaster} style={{ marginLeft: 12 }}>Отвязать от мастера</button>
          )}
        </p>
      ) : (
        <p style={{ color: '#777' }}>Самостоятельный материал (мастера нет)</p>
      )}
      {card.children.length > 0 && (
        <table style={{ borderCollapse: 'collapse', marginBottom: 8 }}>
          <tbody>
            {card.children.map((ch) => (
              <tr key={ch.id}>
                <td>
                  <a href="#" onClick={(e) => { e.preventDefault(); onOpenCard?.(ch.id) }}>{ch.name}</a>
                </td>
                <td style={{ paddingLeft: 12, color: '#777' }}>{STATUS_RU[ch.status]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {card.children.length === 0 && !card.master_id && (
        <p style={{ color: '#777' }}>Подчинённых нет</p>
      )}
      {p.create && (
        <p>
          <button onClick={openChildDialog}>Создать подчинённый материал</button>
        </p>
      )}
      {p.copy && (
        <button onClick={openCopyDialog} style={{ marginRight: 8 }}>Копировать</button>
      )}
      {p.move && card.children.length === 0 && card.status !== 'archived' && (
        <button onClick={openMoveDialog} style={{ marginRight: 8 }}>Переместить</button>
      )}
      {p.edit && card.master_id && card.status !== 'archived' && (
        <button onClick={openMasterDialog}>Сменить мастера</button>
      )}

      {/* Диалог этапа 7: создание подчинённого (US-024/025) */}
      {dialog === 'child' && (
        <div style={dialogBox}>
          <h4>Создать подчинённый материал</h4>
          <label>Вид<br />
            <select value={childKind} onChange={(e) => {
              const kind = e.target.value as 'adaptation' | 'translation'
              setChildKind(kind)
              setChildName(kind === 'translation' ? `${card!.name} (Перевод, …)` : `${card!.name} Адаптация`)
            }}>
              <option value="adaptation">Адаптация</option>
              <option value="translation">Перевод</option>
            </select>
          </label><br /><br />
          {childKind === 'translation' && (
            <>
              <label>Язык перевода (обязателен — US-025 A1)<br />
                <select value={childLang} onChange={(e) => setChildLang(e.target.value)}>
                  <option value="">— выберите язык —</option>
                  {langOptions.map((v) => (
                    <option key={v.id} value={v.id}>{v.value}</option>
                  ))}
                </select>
              </label>{langOptions.length === 0 && (
                <small style={{ color: '#b00' }}> Справочник «Язык» не заведён (СА: атрибуты → справочники)</small>
              )}<br /><br />
            </>
          )}
          <label>Имя (по умолчанию — FR-035)<br />
            <input value={childName} onChange={(e) => setChildName(e.target.value)} style={{ width: 320 }} />
          </label><br /><br />
          <label>Целевая группа<br />
            <select value={targetGroup} onChange={(e) => setTargetGroup(e.target.value)}>
              <option value="">— выберите группу —</option>
              {flatGroups(groups).map(({ g, depth }) => (
                <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
              ))}
            </select>
          </label><br /><br />
          <button onClick={createChild} disabled={busy || !targetGroup || (childKind === 'translation' && !childLang.trim())}>
            Создать
          </button>{' '}
          <button onClick={() => setDialog(null)}>Отмена</button>
        </div>
      )}

      {/* Диалог: копирование (US-028) */}
      {dialog === 'copy' && (
        <div style={dialogBox}>
          <h4>Копировать материал</h4>
          <p style={{ color: '#777' }}>Имя копии: {childName} (счётчик при конфликте — FR-092)</p>
          <label>Целевая группа<br />
            <select value={targetGroup} onChange={(e) => setTargetGroup(e.target.value)}>
              <option value="">— выберите группу —</option>
              {flatGroups(groups).map(({ g, depth }) => (
                <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
              ))}
            </select>
          </label><br /><br />
          <button onClick={doCopy} disabled={busy || !targetGroup}>Копировать</button>{' '}
          <button onClick={() => setDialog(null)}>Отмена</button>
        </div>
      )}

      {/* Диалог: перемещение (US-027) */}
      {dialog === 'move' && (
        <div style={dialogBox}>
          <h4>Переместить материал</h4>
          <p style={{ color: '#777' }}>
            Требуется право «Перемещение» в обеих группах. При конфликте имени операция будет
            отклонена — переименуйте материал вручную (FR-037).
          </p>
          <label>Целевая группа<br />
            <select value={targetGroup} onChange={(e) => setTargetGroup(e.target.value)}>
              <option value="">— выберите группу —</option>
              {flatGroups(groups).map(({ g, depth }) => (
                <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
              ))}
            </select>
          </label><br /><br />
          <button onClick={doMove} disabled={busy || !targetGroup}>Переместить</button>{' '}
          <button onClick={() => setDialog(null)}>Отмена</button>
        </div>
      )}

      {/* Диалог: смена мастера (US-026) */}
      {dialog === 'master' && (
        <div style={dialogBox}>
          <h4>Сменить мастера</h4>
          <p style={{ color: '#777' }}>
            Новый мастер: «Утверждён»/«Публикация», без собственного мастера (FR-032/036).
          </p>
          <label>Поиск материала-мастера<br />
            <input value={masterName} onChange={(e) => searchMasters(e.target.value)}
                   placeholder="Начните вводить название" style={{ width: 320 }} />
          </label>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {masterOptions.map((m) => (
              <li key={m.id}>
                <button onClick={() => changeMaster(m.id)} disabled={busy}>{m.name}</button>
                <small style={{ color: '#777', marginLeft: 8 }}> {STATUS_RU[m.status]}</small>
              </li>
            ))}
          </ul>
          <button onClick={() => setDialog(null)}>Отмена</button>
        </div>
      )}

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

      {/* Этап 7: комментарии (US-038, FR-096–098) */}
      <h3>Комментарии</h3>
      {comments.length === 0 && <p style={{ color: '#777' }}>Комментариев нет</p>}
      <table style={{ borderCollapse: 'collapse', marginBottom: 8 }}>
        <tbody>
          {comments.map((c) => (
            <tr key={c.id}>
              <td style={k}>{fmtDate(c.created_at)}</td>
              <td style={k}>{c.author_id.slice(0, 8)}…</td>
              <td style={{ whiteSpace: 'pre-wrap' }}>{c.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* FR-098: добавляют участники процесса (автор + edit/review/publish);
          право create в карте — не участника; проверка — на сервере */}
      {(p.edit || p.review || p.publish || card.status === 'draft') && (
        <div>
          <textarea
            value={commentText} onChange={(e) => setCommentText(e.target.value)}
            rows={2} style={{ width: 480 }} placeholder="Новый комментарий…"
          /><br />
          <button onClick={addComment} disabled={!commentText.trim() || busy}>Добавить</button>
          <small style={{ color: '#777', marginLeft: 8 }}>
            Комментарии не редактируются и не удаляются (FR-096)
          </small>
        </div>
      )}
    </div>
  )
}

const k: React.CSSProperties = { color: '#666', paddingRight: 16, verticalAlign: 'top', whiteSpace: 'nowrap' }

const dialogBox: React.CSSProperties = {
  border: '1px solid #ccc', borderRadius: 4, padding: '8px 16px',
  maxWidth: 560, margin: '12px 0', background: '#fafafa',
}

const RUS: Record<string, string> = {
  view: 'Просмотр', create: 'Создание', edit: 'Редактирование', delete: 'Удаление',
  review: 'Ревью', publish: 'Публикация', archive: 'Архивация', copy: 'Копирование',
  move: 'Перемещение', download: 'Скачивание', manage_permissions: 'Управление правами',
}
