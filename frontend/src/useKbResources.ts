// Запросы словарей типов/справочников/тегов (FR-043/044/047/052) +
// общая утилита плоского дерева групп (без циклических импортов).
import { api } from './auth'
import { useEffect, useState } from 'react'
import type { DictionaryInfo, GroupNode, MaterialType } from './types'

export type { TypeAttr } from './types'

/** GET /types — с атрибутами (FR-043). */
export function useTypes(): { types: MaterialType[]; error: string } {
  const [types, setTypes] = useState<MaterialType[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    api<MaterialType[]>('/types')
      .then(setTypes)
      .catch((e) => setError(e.detail ?? String(e)))
  }, [])
  return { types, error }
}

/** GET /dictionaries — справочники для dictionary-атрибутов (FR-047). */
export function useDictionaries(): DictionaryInfo[] {
  const [dicts, setDicts] = useState<DictionaryInfo[]>([])
  useEffect(() => {
    api<DictionaryInfo[]>('/dictionaries')
      .then(setDicts)
      .catch(() => setDicts([])) // справочников может не быть — не блокируем форму
  }, [])
  return dicts
}

/** GET /tags — словарь тегов (FR-052, автодополнение US-031 шаг 4). */
export function useTags(): { tags: { id: string; name: string }[]; error: string } {
  const [tags, setTags] = useState<{ id: string; name: string }[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    api<{ id: string; name: string }[]>('/tags')
      .then(setTags)
      .catch((e) => setError(e.detail ?? String(e)))
  }, [])
  return { tags, error }
}

/** Плоское дерево групп для select (раньше дублировалась в MaterialCard). */
export function flatGroups(nodes: GroupNode[], depth = 0): { g: GroupNode; depth: number }[] {
  return nodes.flatMap((n) => [{ g: n, depth }, ...flatGroups(n.children ?? [], depth + 1)])
}
