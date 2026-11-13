// Логика карточки материала (US-037) — вся без JSX: загрузка, правка (If-Match),
// удаление (FR-090), переходы (US-015–021), файл/конвейер (US-011/012),
// скачивание (US-014), версии/diff/restore (US-041/042), связи (этап 7),
// комментарии (US-038). Реорганизация frontend: вынесено из MaterialCard.tsx
// (852 строки); VERSION_CONFLICT обрабатывается в одном месте.
import { useCallback, useEffect, useState } from 'react'
import {
  addComment, copyMaterial, createChild, deleteMaterial, detachMaster,
  downloadMaterial, getComments, getFileState, getMaterial, getStatusLog,
  getTransitions, getVersionDiff, getVersions, listGroupsForDialogs, moveMaterial,
  postTransition, restoreVersion, setMaster, updateMaterial, uploadMaterialFile,
  listMaterials,
} from '../../../api/materials'
import { getLanguageOptions } from '../../../api/references'
import { ApiError } from '../../../api/client'
import { STATUS_RU } from '../../../shared/lib/dicts'
import { errText, versionConflictText } from '../../../shared/lib/errors'
import type {
  CommentInfo, FileState, GroupNode, Material, MaterialCard,
  StatusLogEntry, TransitionInfo, VersionDiff, VersionInfo,
} from '../../../shared/types'

export type CardDialog = 'child' | 'copy' | 'move' | 'master'

/** Состояние и операции карточки. JSX — в MaterialCardView (фича materials). */
export function useMaterialCard(materialId: string, opts: {
  onSaved: () => void
  onClosed: () => void
}) {
  const { onSaved, onClosed } = opts

  const [card, setCard] = useState<MaterialCard | null>(null)
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [transitions, setTransitions] = useState<TransitionInfo[]>([])
  const [log, setLog] = useState<StatusLogEntry[]>([])
  const [fileState, setFileState] = useState<FileState | null>(null)
  const [versions, setVersions] = useState<VersionInfo[]>([])
  const [diff, setDiff] = useState<VersionDiff | null>(null)
  const [busy, setBusy] = useState(false)

  // Диалоги этапа 7: подчинённый/копия/перемещение/мастер
  const [groups, setGroups] = useState<GroupNode[]>([])
  const [langOptions, setLangOptions] = useState<{ id: string; value: string }[]>([])
  const [comments, setComments] = useState<CommentInfo[]>([])
  const [commentText, setCommentText] = useState('')
  const [dialog, setDialog] = useState<CardDialog | null>(null)
  const [childKind, setChildKind] = useState<'adaptation' | 'translation'>('adaptation')
  const [childLang, setChildLang] = useState('')
  const [childName, setChildName] = useState('')
  const [targetGroup, setTargetGroup] = useState('')
  const [masterName, setMasterName] = useState('')
  const [masterOptions, setMasterOptions] = useState<Material[]>([])

  async function load() {
    setError('')
    try {
      const c = await getMaterial(materialId)
      setCard(c)
      setName(c.name)
      setText(c.text_content ?? '')
      // Этап 5: доступные переходы + журнал статусов (FR-070/075)
      const tr = await getTransitions(materialId)
      setTransitions(tr)
      const sl = await getStatusLog(materialId)
      setLog(sl)
      // Этап 6: состояние файла + версии (FR-058/145)
      const fs = await getFileState(materialId)
      setFileState(fs)
      const vs = await getVersions(materialId)
      setVersions(vs)
      setDiff(null)
    } catch (e) {
      setError(errText(e))
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [materialId])

  async function save() {
    if (!card) return
    setSaving(true)
    setError('')
    try {
      await updateMaterial(card.id, card.version, { name, text_content: text })
      setEditing(false)
      await load()
      onSaved()
    } catch (e) {
      const conflict = versionConflictText(e)
      if (conflict) {
        setError(conflict)
        await load()
      } else {
        setError(errText(e))
      }
    } finally {
      setSaving(false)
    }
  }

  async function remove() {
    if (!card || !window.confirm(`Удалить «${card.name}»?`)) return
    setError('')
    try {
      await deleteMaterial(card.id, card.version)
      onSaved()
      onClosed()
    } catch (e) {
      setError(errText(e))
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
      await postTransition(card.id, card.version, {
        to_status: t.to_status, confirm_cascade: confirmCascade,
      })
      await load()
      onSaved()
    } catch (e) {
      const conflict = versionConflictText(e)
      if (conflict) {
        setError(conflict)
        await load()
      } else {
        setError(errText(e))
      }
    }
  }

  // Этап 6: загрузка файла (§6.2); offer_text_update — диалог FR-030
  async function uploadFile(file: File) {
    if (!card) return
    setBusy(true)
    setError('')
    try {
      const r = await uploadMaterialFile(card.id, file)
      if (r.offer_text_update) {
        const yes = window.confirm('Обновить текстовое представление содержимым файла?')
        await uploadMaterialFile(card.id, file, yes ? 'replace' : 'keep')
      }
      await load()
      onSaved()
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  // Этап 6: скачивание исходника/.md через api-стриминг (§6.4, FR-067/107)
  async function download(kind: 'file' | 'text.md' | 'pdf') {
    if (!card) return
    setError('')
    try {
      const r = await downloadMaterial(kind, card.id)
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
      setError(errText(e))
    }
  }

  // Этап 6: diff соседних версий (US-041 шаг 2)
  async function showDiff(n: number) {
    setError('')
    try {
      setDiff(await getVersionDiff(card!.id, n))
    } catch (e) {
      setError(errText(e))
    }
  }

  // ===== Этап 7: мастер-подчинённый, move/copy, комментарии =====

  useEffect(() => {
    if (card) {
      listGroupsForDialogs().then(setGroups).catch(() => setGroups([]))
      // Справочник атрибута «Язык» (FR-046): значения для диалога перевода
      getLanguageOptions().then(setLangOptions).catch(() => setLangOptions([]))
    }
  }, [card?.id])

  useEffect(() => {
    getComments(materialId)
      .then(setComments)
      .catch(() => setComments([]))
  }, [materialId, card?.version])

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

  function openMasterDialog() {
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
      const r = await listMaterials('/?sort=name&order=asc&per_page=10&status=approved')
      const r2 = await listMaterials('/?sort=name&order=asc&per_page=10&status=published')
      const all = [...r.items, ...r2.items].filter(
        (m) => m.id !== card?.id && m.name.toLowerCase().includes(q.trim().toLowerCase()),
      )
      setMasterOptions(all)
    } catch {
      setMasterOptions([])
    }
  }

  function defaultChildName(): string {
    if (!card) return ''
    return childKind === 'translation' ? `${card.name} (Перевод, …)` : `${card.name} Адаптация`
  }

  async function createChildSubmit() {
    if (!card || !targetGroup) return
    setBusy(true)
    setError('')
    try {
      const body: Record<string, unknown> = {
        kind: childKind, group_id: targetGroup,
      }
      if (childName.trim() && childName.trim() !== defaultChildName()) body.name = childName.trim()
      if (childKind === 'translation') body.language_id = childLang
      await createChild(card.id, body as Parameters<typeof createChild>[1])
      setDialog(null)
      await load()
      onSaved()
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  async function doCopy() {
    if (!card || !targetGroup) return
    setBusy(true)
    setError('')
    try {
      await copyMaterial(card.id, { group_id: targetGroup, name: childName })
      setDialog(null)
      onSaved()
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  async function doMove() {
    if (!card || !targetGroup) return
    setBusy(true)
    setError('')
    try {
      await moveMaterial(card.id, { group_id: targetGroup })
      setDialog(null)
      await load()
      onSaved()
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  async function changeMaster(newMasterId: string) {
    if (!card) return
    setBusy(true)
    setError('')
    try {
      await setMaster(card.id, newMasterId)
      setDialog(null)
      await load()
      onSaved()
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  async function detachMasterAction() {
    if (!card || !window.confirm('Отвязать материал от мастера? Материал станет самостоятельным.')) return
    setError('')
    try {
      await detachMaster(card.id)
      await load()
      onSaved()
    } catch (e) {
      setError(errText(e))
    }
  }

  async function addCommentAction() {
    if (!card || !commentText.trim()) return
    setError('')
    try {
      await addComment(card.id, commentText)
      setCommentText('')
      setComments(await getComments(card.id))
    } catch (e) {
      setError(errText(e))
    }
  }

  // Этап 6: восстановление версии (US-042, FR-148)
  async function restore(n: number) {
    if (!card || !window.confirm(`Восстановить версию ${n}? Текущее содержимое будет заменено (создаётся новая версия).`)) return
    setError('')
    try {
      await restoreVersion(card.id, n, card.version)
      await load()
      onSaved()
    } catch (e) {
      const conflict = versionConflictText(e)
      if (conflict) {
        setError(conflict)
        await load()
      } else {
        setError(errText(e))
      }
    }
  }

  /** Плоское дерево для select'ов диалогов (см. shared/lib/groups). */
  const flatForSelect = useCallback(function flat(nodes: GroupNode[], depth = 0): { g: GroupNode; depth: number }[] {
    return nodes.flatMap((n) => [{ g: n, depth }, ...flat(n.children ?? [], depth + 1)])
  }, [])

  return {
    // данные
    card, transitions, log, fileState, versions, diff, comments, groups, langOptions,
    // поля формы
    name, setName, text, setText, editing, setEditing, commentText, setCommentText,
    // диалоги
    dialog, setDialog, childKind, setChildKind, childLang, setChildLang,
    childName, setChildName, targetGroup, setTargetGroup,
    masterName, setMasterName, masterOptions, searchMasters,
    // состояние
    error, saving, busy,
    // операции
    save, remove, doTransition, uploadFile, download, showDiff, restore,
    openChildDialog, openCopyDialog, openMoveDialog, openMasterDialog,
    createChildSubmit, doCopy, doMove, changeMaster, detachMasterAction, addCommentAction,
    flatForSelect,
  }
}
