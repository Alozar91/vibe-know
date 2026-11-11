// Перечень групп + список материалов (US-005): группы и view - это содержание,
// остальное - параметры выборки (FR-103); сортировка/пагинация FR-117/121.
// Этап: создание материала (US-007/008) и управление группами СА (US-052).
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './auth'
import { fmtDate, type GroupNode, type Material, type Page } from './types'
import { Empty, Err, Pager, StatusBadge } from './ui'
import CreateMaterialDialog from './CreateMaterialDialog'
import { flatGroups } from './useKbResources'

interface Props {
  onOpenMaterial: (id: string) => void
  refreshToken: number // для перезагрузки (после действий)
  isSuper: boolean // СА — управление группами (US-052)
}

// Диалог групповых операций СА: create/rename/delete (delete двухшаговый —
// подтверждение прав RIGHTS_CONFIRM_REQUIRED обрабатывает сам диалог, US-052 шаг 4)
type GroupDialog =
  | { kind: 'create'; parent: GroupNode | null }
  | { kind: 'rename'; group: GroupNode }
  | { kind: 'delete'; group: GroupNode }

function errText(e: unknown): string {
  return e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e)
}

export default function MaterialsBrowser({ onOpenMaterial, refreshToken, isSuper }: Props) {
  const [tree, setTree] = useState<GroupNode[]>([])
  const [selected, setSelected] = useState<GroupNode | null>(null)
  const [items, setItems] = useState<Material[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState('updated_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [groupDialog, setGroupDialog] = useState<GroupDialog | null>(null)
  const PER_PAGE = 50 // FR-121

  useEffect(() => {
    api<GroupNode[]>('/groups')
      .then((t) => {
        setTree(t)
        // выбранная группа могла исчезнуть (удалена СА / скрыта) — сброс выбора
        setSelected((prev) => (prev && !flatGroups(t).some(({ g }) => g.id === prev.id) ? null : prev))
      })
      .catch((e) => setError(e.detail ?? String(e)))
  }, [refreshToken])

  const loadList = useCallback(() => {
    if (!selected) return
    setError('')
    api<Page<Material>>(`/materials?group_id=${selected.id}&page=${page}&per_page=${PER_PAGE}&sort=${sort}&order=${order}`)
      .then((p) => { setItems(p.items); setTotal(p.total) })
      .catch((e) => setError(e.detail ?? String(e)))
  }, [selected, page, sort, order])

  useEffect(() => { loadList() }, [loadList, refreshToken])

  function changeSort(col: string) {
    if (sort === col) setOrder(order === 'asc' ? 'desc' : 'asc')
    else { setSort(col); setOrder('asc') }
  }

  const pages = Math.max(1, Math.ceil(total / PER_PAGE))

  // ===== Действия СА над группами (US-052) =====

  async function reloadTree() {
    try {
      const t = await api<GroupNode[]>('/groups')
      setTree(t)
      setSelected((prev) => (prev && !flatGroups(t).some(({ g }) => g.id === prev.id) ? null : prev))
      // список выбранной группы мог измениться (soft-delete ветки)
      loadList()
    } catch (e) {
      setError(errText(e))
    }
  }

  function errText(e: unknown): string {
    return e instanceof ApiError ? `${e.title}: ${e.detail ?? ''}` : String(e)
  }

  return (
    <div>
      <div className="pagehead">
        <h2>{selected ? selected.name : 'Материалы'}</h2>
        {selected && <span className="total-pill">{total}</span>}
      </div>
      <div className="browser">
        <aside className="side-in-panel">
          <h4>Группы</h4>
          <GroupTreeView nodes={tree} selected={selected} onSelect={(g) => { setSelected(g); setPage(1) }} />
          {isSuper && (
            <div className="btnrow">
              <button className="btn small" onClick={() => setGroupDialog({ kind: 'create', parent: null })}>
                + Группа (корень)
              </button>
              {selected && (
                <>
                  <button className="btn small" onClick={() => setGroupDialog({ kind: 'create', parent: selected })}>
                    + Подгруппа
                  </button>
                  <button className="btn small" onClick={() => setGroupDialog({ kind: 'rename', group: selected })}>
                    Переименовать
                  </button>
                  <button className="btn danger small" onClick={() => setGroupDialog({ kind: 'delete', group: selected })}>
                    Удалить
                  </button>
                </>
              )}
            </div>
          )}
        </aside>
        <section className="browser-list">
          <Err>{error}</Err>
          {selected ? (
            <div className="panel">
              <div className="toolbar">
                <span className="meta">Сортировка: {sort === 'updated_at' ? 'по изменению' : 'по статусу'} {order === 'asc' ? '↑' : '↓'}</span>
                <span className="spacer" />
                <span className="meta">Страница {page} из {pages}</span>
                <button className="btn primary small" onClick={() => setCreating(true)} title="Создать материал в выбранной группе (US-007/008)">
                  + Создать материал
                </button>
              </div>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Название</th>
                    <th className="sortable" onClick={() => changeSort('status')}>Статус</th>
                    <th className="sortable" onClick={() => changeSort('updated_at')}>
                      Изменён {sort === 'updated_at' && <span className="arr">{order === 'asc' ? '↑' : '↓'}</span>}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((m) => (
                    <tr key={m.id} className="rowlink" onClick={() => onOpenMaterial(m.id)}>
                      <td className="mname">{m.name}</td>
                      <td><StatusBadge status={m.status} /></td>
                      <td className="nowrap">{fmtDate(m.updated_at)}</td>
                    </tr>
                  ))}
                  {items.length === 0 && !error && (
                    <tr><td colSpan={3}><Empty>В этой группе пока нет материалов</Empty></td></tr>
                  )}
                </tbody>
              </table>
              {pages > 1 && <Pager page={page} pages={pages} total={total} onPrev={() => setPage(page - 1)} onNext={() => setPage(page + 1)} />}
            </div>
          ) : (
            <Empty>Выберите группу в дереве слева (US-005).</Empty>
          )}
        </section>
      </div>

      {/* Диалог создания материала (US-007/008) */}
      {creating && selected && (
        <div className="dialog">
          <CreateMaterialDialog
            group={selected}
            tree={tree}
            onCreated={(id) => { setCreating(false); reloadTree(); onOpenMaterial(id) }}
            onCancel={() => setCreating(false)}
          />
        </div>
      )}

      {/* Диалоги групп СА (US-052) */}
      {groupDialog?.kind === 'create' && (
        <GroupFormDialog
          parent={groupDialog.parent}
          tree={tree}
          onDone={() => { setGroupDialog(null); reloadTree() }}
          onCancel={() => setGroupDialog(null)}
        />
      )}
      {groupDialog?.kind === 'rename' && (
        <GroupFormDialog
          rename={groupDialog.group}
          tree={tree}
          onDone={() => { setGroupDialog(null); reloadTree() }}
          onCancel={() => setGroupDialog(null)}
        />
      )}
      {groupDialog?.kind === 'delete' && (
        <GroupDeleteDialog
          group={groupDialog.group}
          onDone={() => { setGroupDialog(null); reloadTree() }}
          onCancel={() => setGroupDialog(null)}
        />
      )}
    </div>
  )
}

function GroupTreeView({ nodes, selected, onSelect, depth = 0 }: {
  nodes: GroupNode[]
  selected: GroupNode | null
  onSelect: (g: GroupNode) => void
  depth?: number
}) {
  return (
    <ul className="tree">
      {nodes.map((g) => (
        <li key={g.id}>
          <div className={`g ${selected?.id === g.id ? 'on' : ''}`} onClick={() => onSelect(g)}>
            <span className="fi">📁</span> {g.name}
          </div>
          {g.children && g.children.length > 0 && (
            <GroupTreeView nodes={g.children} selected={selected} onSelect={onSelect} depth={depth + 1} />
          )}
        </li>
      ))}
    </ul>
  )
}

// ===== Диалоги СА: создание/переименование, удаление (US-052) =====

function GroupFormDialog({ parent, rename, tree, onDone, onCancel }: {
  parent?: GroupNode | null // режим создания: родитель (null = корень)
  rename?: GroupNode // режим переименования
  tree: GroupNode[]
  onDone: () => void
  onCancel: () => void
}) {
  const isRename = !!rename
  const [name, setName] = useState(rename?.name ?? '')
  const [parentId, setParentId] = useState(parent?.id ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    setError('')
    if (!name.trim()) { setError('Укажите название группы'); return }
    setBusy(true)
    try {
      if (isRename) {
        await api(`/groups/${rename!.id}`, { method: 'PATCH', body: JSON.stringify({ name: name.trim() }) })
      } else {
        await api('/groups', {
          method: 'POST',
          body: JSON.stringify({ name: name.trim(), parent_id: parentId || null }),
        })
      }
      onDone()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'NAME_CONFLICT') {
        // FR-017: дубль среди подгрупп родителя (без учёта регистра, «е»/«ё» различны)
        setError('Группа с таким названием уже есть на этом уровне (FR-017).')
      } else {
        setError(errText(e))
      }
      setBusy(false)
    }
  }

  return (
    <div className="dialog">
      <h4>{isRename ? `Переименовать «${rename!.name}»` : parent ? `Создать подгруппу в «${parent.name}»` : 'Создать корневую группу'}</h4>
      <label className="field">
        <span className="lbl">Название (до 255 символов — FR-017)</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} />
      </label>
      {!isRename && (
        <label className="field">
          <span className="lbl">Родительская группа (вложенность не ограничена — FR-016)</span>
          <select value={parentId} onChange={(e) => setParentId(e.target.value)}>
            <option value="">— корень —</option>
            {flatGroups(tree).map(({ g, depth }) => (
              <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
            ))}
          </select>
        </label>
      )}
      <Err>{error}</Err>
      <div className="btnrow">
        <button className="btn primary" onClick={submit} disabled={busy || !name.trim()}>
          {busy ? 'Сохранение…' : 'Сохранить'}
        </button>
        <button className="btn ghost" onClick={onCancel} disabled={busy}>Отмена</button>
      </div>
    </div>
  )
}

function GroupDeleteDialog({ group, onDone, onCancel }: {
  group: GroupNode
  onDone: () => void
  onCancel: () => void
}) {
  const [needRightsConfirm, setNeedRightsConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function doDelete(confirmRights: boolean) {
    setBusy(true)
    setError('')
    try {
      const r = await api<{ mode: 'hard' | 'soft'; subtree_count: number }>(
        `/groups/${group.id}${confirmRights ? '?confirm_rights=true' : ''}`,
        { method: 'DELETE' },
      )
      window.alert(r.mode === 'hard'
        ? 'Группа удалена (пустая — физически, FR-018).'
        : `Ветка удалена: скрыто групп — ${r.subtree_count} (soft-delete, FR-019).`)
      onDone()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'RIGHTS_CONFIRM_REQUIRED') {
        // US-052 шаг 4: на группу назначены права — требуется подтверждение
        setNeedRightsConfirm(true)
        setError('На группу назначены права. Нажмите «Удалить с правами», чтобы удалить их вместе с группой (FR-018).')
      } else {
        setError(errText(e))
      }
      setBusy(false)
    }
  }

  return (
    <div className="dialog">
      <h4>Удалить «{group.name}»?</h4>
      <p className="note">
        Пустая группа (без подгрупп и материалов) удаляется физически; непустая ветка —
        скрывается целиком (soft-delete, FR-019). Мастер-материал с подчинёнными вне
        ветки блокирует удаление (FR-020).
      </p>
      {needRightsConfirm && (
        <div className="alert warn">На группу назначены права — будут удалены вместе с группой (FR-018).</div>
      )}
      <Err>{error}</Err>
      <div className="btnrow">
        <button className="btn danger" onClick={() => doDelete(needRightsConfirm)} disabled={busy}>
          {busy ? 'Удаление…' : (needRightsConfirm ? 'Удалить с правами' : 'Удалить')}
        </button>
        <button className="btn ghost" onClick={onCancel} disabled={busy}>Отмена</button>
      </div>
    </div>
  )
}
