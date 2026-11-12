// Плоское дерево групп для select'ов (раньше дублировалось в useKbResources
// и внутри MaterialCard).
import type { GroupNode } from '../types'

export function flatGroups(nodes: GroupNode[], depth = 0): { g: GroupNode; depth: number }[] {
  return nodes.flatMap((n) => [{ g: n, depth }, ...flatGroups(n.children ?? [], depth + 1)])
}
