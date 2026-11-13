// Форма создания материала (US-007/008): название, тип, группа (предзаполнена),
// текст, атрибуты (обязательные — FR-048), теги (FR-052); файл — сразу после
// создания через POST /materials/{id}/file с диалогом FR-030 (offer_text_update).
// Реорганизация frontend: справочные хуки — из shared/hooks (TanStack Query),
// вызовы — через src/api.
import { useMemo, useState } from 'react'
import { ApiError } from '../../../api/client'
import { createMaterial, uploadMaterialFile } from '../../../api/materials'
import { useDictionaries, useTags, useTypes, type TypeAttr } from '../../../shared/hooks/resources'
import { flatGroups } from '../../../shared/lib/groups'
import { errText } from '../../../shared/lib/errors'
import { Err } from '../../../shared/ui/index'
import type { DictionaryInfo, GroupNode, MaterialType } from '../../../shared/types'

interface Props {
  group: GroupNode // предзаполнение группы (US-007 шаг 2)
  tree: GroupNode[]
  onCreated: (materialId: string) => void
  onCancel: () => void
}

// Значения одного атрибута в форме: строка ввода; multivalue — через «;»
interface AttrDraft {
  raw: string
}

const VALUE_TYPE_RU: Record<TypeAttr['value_type'], string> = {
  string: 'строка',
  number: 'число',
  date: 'дата',
  url: 'URL',
  dictionary: 'из справочника',
}

/** Разбор multivalue-ввода «a; b; c» → массив значений. */
function splitValues(raw: string, multivalue: boolean): string[] {
  const parts = multivalue ? raw.split(';') : [raw]
  return parts.map((s) => s.trim()).filter((s) => s !== '')
}

/** Фронтенд-каст для number (бэкенд валидирует окончательно — FR-044). */
function castValue(a: TypeAttr, v: string): unknown {
  if (a.value_type === 'number') {
    const n = Number(v)
    return Number.isFinite(n) ? n : v // невалидное — пусть бэкенд вернёт понятную ошибку
  }
  return v
}

export default function CreateMaterialDialog({ group, tree, onCreated, onCancel }: Props) {
  const { types, error: typesErr } = useTypes()
  const dicts = useDictionaries()
  const { tags } = useTags()

  const [name, setName] = useState('')
  const [typeId, setTypeId] = useState('')
  const [groupId, setGroupId] = useState(group.id)
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [attrDrafts, setAttrDrafts] = useState<Record<string, AttrDraft>>({})
  const [tagIds, setTagIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const type = useMemo<MaterialType | undefined>(
    () => types.find((t) => t.id === typeId),
    [types, typeId],
  )
  const attrs: TypeAttr[] = type?.attributes ?? []

  const flat = useMemo(() => flatGroups(tree), [tree])

  /** Справочник dictionary-атрибута (значения для select). */
  function dictFor(a: TypeAttr): DictionaryInfo | undefined {
    return a.dictionary_id ? dicts.find((d) => d.id === a.dictionary_id) : undefined
  }

  /** Клиентская проверка обязательных атрибутов (FR-048); полная — на бэкенде. */
  const missingRequired = useMemo(
    () => attrs.filter((a) => {
      if (!a.is_required) return false
      const vals = splitValues(attrDrafts[a.id]?.raw ?? '', a.is_multivalue)
      return vals.length === 0
    }).map((a) => a.name),
    [attrs, attrDrafts],
  )

  function setDraft(attrId: string, raw: string) {
    setAttrDrafts((prev) => ({ ...prev, [attrId]: { raw } }))
  }

  async function submit() {
    setError('')
    if (!name.trim()) { setError('Укажите название материала'); return }
    if (!typeId) { setError('Укажите тип материала'); return }
    if (missingRequired.length > 0) {
      setError(`Заполните обязательные атрибуты: ${missingRequired.join(', ')}`)
      return
    }
    setBusy(true)
    try {
      // attribute_values: [{attribute_id, values: [...]}] (LLD §12.3)
      const attribute_values = attrs
        .map((a) => ({
          attribute_id: a.id,
          values: splitValues(attrDrafts[a.id]?.raw ?? '', a.is_multivalue)
            .map((v) => castValue(a, v)),
        }))
        .filter((x) => x.values.length > 0)
      const created = await createMaterial({
        name: name.trim(),
        group_id: groupId,
        type_id: typeId,
        text_content: text.trim() || null,
        attribute_values,
        tag_ids: tagIds,
      })
      // Файл — сразу после создания (§6.2): диалог FR-030 при непустом тексте.
      // Если файл не принят (тип/размер/антивирус) — материал уже существует:
      // открываем карточку, файл догружается там штатно (US-008)
      if (file) {
        try {
          await uploadFileAfterCreate(created.id, file)
        } catch (fe) {
          window.alert(
            'Материал создан, но файл не загружен: '
            + (fe instanceof ApiError ? [fe.title, fe.detail].filter(Boolean).join(': ') : String(fe))
            + '. Загрузите файл в карточке материала.',
          )
        }
      }
      onCreated(created.id)
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.code === 'NAME_CONFLICT') {
          setError('Материал с таким названием уже есть в этой группе (US-007 A1).')
        } else if (e.code === 'ATTRIBUTE_REQUIRED_MISSING') {
          const missing = (e.params?.missing as string[] | undefined) ?? []
          setError(`Заполните обязательные атрибуты: ${missing.join(', ')}`)
        } else if (e.code === 'ACCESS_DENIED') {
          setError('Нет права «Создание» в выбранной группе (US-007 A4).')
        } else {
          setError([e.title, e.detail].filter(Boolean).join(': ') || String(e))
        }
      } else {
        setError(errText(e))
      }
      setBusy(false)
    }
  }

  /** Загрузка файла §6.2 (как uploadFile в карточке): offer_text_update — FR-030. */
  async function uploadFileAfterCreate(materialId: string, f: File) {
    const r = await uploadMaterialFile(materialId, f)
    if (r.offer_text_update) {
      const yes = window.confirm('Обновить текстовое представление содержимым файла?')
      await uploadMaterialFile(materialId, f, yes ? 'replace' : 'keep')
    }
  }

  return (
    <div className="dialog">
      <h4>Создать материал — {group.name}</h4>
      <Err>{typesErr}</Err>
      <label className="field">
        <span className="lbl">Название *</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} />
      </label>
      <label className="field">
        <span className="lbl">Тип *</span>
        <select value={typeId} onChange={(e) => setTypeId(e.target.value)}>
          <option value="">— выберите тип —</option>
          {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </label>
      <label className="field">
        <span className="lbl">Группа *</span>
        <select value={groupId} onChange={(e) => setGroupId(e.target.value)}>
          {flat.map(({ g, depth }) => (
            <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="lbl">Файл (до 100 МБ — FR-031; можно загрузить позже в карточке)</span>
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span className="lbl">Текст (Markdown; для .md/.txt заполнится из файла — FR-029)</span>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} />
      </label>

      {/* Атрибуты выбранного типа (FR-048): обязательные помечены */}
      {attrs.length > 0 && (
        <div className="fld">
          <label>Атрибуты</label>
          {attrs.map((a) => {
            const d = dictFor(a)
            const raw = attrDrafts[a.id]?.raw ?? ''
            if (a.value_type === 'dictionary' && d) {
              return (
                <label className="field" key={a.id}>
                  <span className="lbl">
                    {a.name}{a.is_required && ' *'} <small className="note">({VALUE_TYPE_RU[a.value_type]})</small>
                  </span>
                  <select value={raw} onChange={(e) => setDraft(a.id, e.target.value)}>
                    <option value="">— не выбрано —</option>
                    {d.value_items.map((v) => <option key={v.id} value={v.id}>{v.value}</option>)}
                  </select>
                </label>
              )
            }
            if (a.value_type === 'date') {
              return (
                <label className="field" key={a.id}>
                  <span className="lbl">{a.name}{a.is_required && ' *'} <small className="note">(дата)</small></span>
                  <input type="date" value={raw} onChange={(e) => setDraft(a.id, e.target.value)} />
                </label>
              )
            }
            return (
              <label className="field" key={a.id}>
                <span className="lbl">
                  {a.name}{a.is_required && ' *'} <small className="note">({VALUE_TYPE_RU[a.value_type]}{a.is_multivalue ? '; несколько — через «;»' : ''})</small>
                </span>
                <input
                  value={raw}
                  onChange={(e) => setDraft(a.id, e.target.value)}
                  placeholder={a.value_type === 'url' ? 'https://…' : undefined}
                />
              </label>
            )
          })}
          {missingRequired.length > 0 && (
            <div className="alert warn">Не заполнены обязательные: {missingRequired.join(', ')}</div>
          )}
        </div>
      )}

      {/* Теги (FR-052): чекбоксы из словаря */}
      {tags.length > 0 && (
        <div className="fld">
          <label>Теги</label>
          <div className="formrow">
            {tags.map((t) => (
              <label key={t.id} className="tagopt">
                <input
                  type="checkbox"
                  checked={tagIds.includes(t.id)}
                  onChange={(e) => setTagIds((prev) => e.target.checked ? [...prev, t.id] : prev.filter((x) => x !== t.id))}
                /> {t.name}
              </label>
            ))}
          </div>
        </div>
      )}

      <Err>{error}</Err>
      <div className="btnrow">
        <button className="btn primary" onClick={submit} disabled={busy || !name.trim() || !typeId || missingRequired.length > 0}>
          {busy ? 'Создание…' : 'Создать'}
        </button>
        <button className="btn ghost" onClick={onCancel} disabled={busy}>Отмена</button>
      </div>
    </div>
  )
}
