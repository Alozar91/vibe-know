// Справочные ресурсы: типы, справочники, теги, атрибуты (FR-043/044/046/047/052).
import { api } from './client'
import type { DictionaryInfo, MaterialType } from '../shared/types'

/** GET /types — типы материалов с атрибутами (FR-043). */
export function getTypes(): Promise<MaterialType[]> {
  return api<MaterialType[]>('/types')
}

/** GET /dictionaries — справочники (FR-047; могут отсутствовать — не блокирует форму). */
export function getDictionaries(): Promise<DictionaryInfo[]> {
  return api<DictionaryInfo[]>('/dictionaries')
}

/** GET /tags — словарь тегов (FR-052). */
export function getTags(): Promise<{ id: string; name: string }[]> {
  return api<{ id: string; name: string }[]>('/tags')
}

/** GET /attributes — атрибуты (для поиска словаря «Язык», FR-046).
 *  Формат ответа менялся: массив или {items} — нормализуем к массиву. */
export function getAttributes(): Promise<{ id: string; name: string; dictionary_id?: string | null }[]> {
  return api<{ items?: { id: string; name: string; dictionary_id?: string | null }[] }
    | { id: string; name: string; dictionary_id?: string | null }[]>('/attributes')
    .then((raw) => Array.isArray(raw) ? raw : (raw.items ?? []))
}

/** Значения справочника атрибута «Язык» (диалог перевода, US-025). */
export function getLanguageOptions(): Promise<{ id: string; value: string }[]> {
  return Promise.all([getDictionaries().catch(() => []), getAttributes().catch(() => [])])
    .then(([dicts, attrs]) => {
      const lang = attrs.find((x) => x.name === 'Язык')
      const d = lang?.dictionary_id ? dicts.find((x) => x.id === lang.dictionary_id) : undefined
      return d?.value_items ?? []
    })
}
