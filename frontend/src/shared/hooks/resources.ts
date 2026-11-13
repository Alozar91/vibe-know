// Общие TanStack Query-хуки справочных ресурсов (FR-043/044/047/052)
// и дерево групп. Реорганизация frontend: раньше — useKbResources.ts
// с ручными useState/useEffect.
import { useQuery } from '@tanstack/react-query'
import { getDictionaries, getTags, getTypes } from '../../api/references'
import { getGroupTree } from '../../api/groups'
import type { DictionaryInfo, GroupNode, MaterialType } from '../types'

export type { TypeAttr } from '../types'

/** GET /types — с атрибутами (FR-043). */
export function useTypes(): { types: MaterialType[]; error: string } {
  const q = useQuery({ queryKey: ['types'], queryFn: getTypes, staleTime: 5 * 60_000 })
  return { types: q.data ?? [], error: q.error ? (q.error as Error).message : '' }
}

/** GET /dictionaries — справочники для dictionary-атрибутов (FR-047).
 *  Справочников может не быть — не блокируем форму (ошибки глушатся). */
export function useDictionaries(): DictionaryInfo[] {
  const q = useQuery({
    queryKey: ['dictionaries'],
    queryFn: () => getDictionaries().catch(() => [] as DictionaryInfo[]),
    staleTime: 5 * 60_000,
  })
  return q.data ?? []
}

/** GET /tags — словарь тегов (FR-052, автодополнение US-031 шаг 4). */
export function useTags(): { tags: { id: string; name: string }[]; error: string } {
  const q = useQuery({ queryKey: ['tags'], queryFn: getTags, staleTime: 5 * 60_000 })
  return { tags: q.data ?? [], error: q.error ? (q.error as Error).message : '' }
}

/** GET /groups — дерево видимых групп (FR-016/109). */
export function useGroupTree(): { tree: GroupNode[]; error: string; reload: () => void } {
  const q = useQuery({ queryKey: ['groups'], queryFn: getGroupTree })
  return {
    tree: q.data ?? [],
    error: q.error ? (q.error as Error).message : '',
    reload: () => void q.refetch(),
  }
}
