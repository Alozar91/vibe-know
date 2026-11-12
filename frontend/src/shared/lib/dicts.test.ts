// Тесты словарей/форматтеров и хелперов ошибок.
import { describe, expect, it } from 'vitest'
import {
  EVENT_TITLES, PDF_RU, PERMISSIONS_RU, SCAN_RU, STATUS_RU, fmtDate, fmtDateTime,
} from './dicts'
import { errText, versionConflictText } from './errors'
import { flatGroups } from './groups'
import { ApiError } from '../../api/client'
import type { GroupNode } from '../types'

describe('dicts', () => {
  it('STATUS_RU покрывает все пять статусов жизненного цикла (§4.1)', () => {
    expect(Object.keys(STATUS_RU).sort()).toEqual(
      ['approved', 'archived', 'draft', 'in_review', 'published'].sort(),
    )
  })

  it('SCAN_RU/PDF_RU/PERMISSIONS_RU/EVENT_TITLES непусты и без дублей-значений', () => {
    expect(Object.keys(SCAN_RU)).toHaveLength(4)
    expect(Object.keys(PDF_RU)).toHaveLength(4)
    expect(PERMISSIONS_RU['manage_permissions']).toBe('Управление правами')
    expect(EVENT_TITLES['material_sent_to_review']).toContain('проверку')
  })

  it('fmtDate: пусто → тире; валидная дата → строка с годом', () => {
    expect(fmtDate(null)).toBe('—')
    expect(fmtDate(undefined)).toBe('—')
    expect(fmtDate('2026-11-12T10:00:00Z')).toMatch(/2026/)
    expect(fmtDateTime(null)).toBe('—')
  })
})

describe('errors', () => {
  it('errText: ApiError → «title: detail», обычная ошибка → message', () => {
    const e = new ApiError(412, 'VERSION_CONFLICT', 'Конфликт версий', 'подробно')
    expect(errText(e)).toBe('Конфликт версий: подробно')
    expect(errText(new Error('сбой'))).toBe('сбой')
    expect(errText('строка')).toBe('строка')
  })

  it('versionConflictText: только для ApiError VERSION_CONFLICT', () => {
    expect(versionConflictText(new ApiError(412, 'VERSION_CONFLICT', 'Конфликт'))).toMatch(/другим пользователем/)
    expect(versionConflictText(new ApiError(403, 'ACCESS_DENIED', 'Нет'))).toBeNull()
    expect(versionConflictText(new Error('x'))).toBeNull()
  })
})

describe('flatGroups', () => {
  it('разворачивает дерево с глубиной', () => {
    const tree: GroupNode[] = [
      { id: '1', name: 'A', parent_id: null, path: 'A', children: [
        { id: '2', name: 'B', parent_id: '1', path: 'A/B' },
      ] },
      { id: '3', name: 'C', parent_id: null, path: 'C' },
    ]
    const flat = flatGroups(tree)
    expect(flat.map((x) => x.g.id)).toEqual(['1', '2', '3'])
    expect(flat.map((x) => x.depth)).toEqual([0, 1, 0])
  })
})
