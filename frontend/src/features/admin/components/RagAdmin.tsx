// RAG (пост-MVP шаг [7] ч.4, RAG_DESIGN §8-4) — только СА:
// 1) статус индексации (§8-4): счётчики + проблемные материалы, ручная
//    переиндексация; 2) конфигурация чанкования групп (§3): явная настройка
//    или наследование; 3) проверка embedding-провайдера (§6).
// Реорганизация frontend: вызовы — через src/api/admin; дерево групп —
// TanStack Query. Три таба — внутреннее состояние фичи (useState).
import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  deleteRagGroupConfig, getRagGroupConfig, getRagStatus, reindexGroupSubtree,
  reindexMaterial, testRagConnection, updateRagGroupConfig,
  type RagConfigOut, type RagStatus,
} from '../../../api/admin'
import { getGroupTree } from '../../../api/groups'
import { errText, fmtDate } from '../../../shared/lib/dicts'
import { Empty, Err, Loading, Ok } from '../../../shared/ui/index'
import type { GroupNode } from '../../../shared/types'

const STATE_RU: Record<string, string> = {
  none: 'не индексируется',
  pending: 'в очереди',
  indexed: 'проиндексировано',
  error: 'ошибка',
}

// Тон числа статкарточки: цвета из палитры темы (styles.css §1)
const TONE_COLOR: Record<string, string> = {
  ok: 'var(--okfg)',
  warn: 'var(--warnfg)',
  err: 'var(--danger)',
}

export default function RagAdmin({ onOpenMaterial }: { onOpenMaterial: (id: string) => void }) {
  const [tab, setTab] = useState<'status' | 'config' | 'conn'>('status')

  return (
    <div>
      <div className="pagehead"><h2>RAG — векторный поиск</h2></div>
      <div className="chiprow">
        <button className={`chip ${tab === 'status' ? 'on' : ''}`} onClick={() => setTab('status')}>Статус индексации</button>
        <button className={`chip ${tab === 'config' ? 'on' : ''}`} onClick={() => setTab('config')}>Чанкование групп</button>
        <button className={`chip ${tab === 'conn' ? 'on' : ''}`} onClick={() => setTab('conn')}>Embedding-провайдер</button>
      </div>

      {tab === 'status' && <StatusTab onOpenMaterial={onOpenMaterial} />}
      {tab === 'config' && <ConfigTab />}
      {tab === 'conn' && <ConnectionTab />}
    </div>
  )
}

// ---------------------------------------------------------------- статус
function StatusTab({ onOpenMaterial }: { onOpenMaterial: (id: string) => void }) {
  const [data, setData] = useState<RagStatus | null>(null)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    getRagStatus()
      .then((d) => { setData(d); setError('') })
      .catch((e) => setError(errText(e)))
  }, [])
  useEffect(() => { load() }, [load])

  const reindexAll = async () => {
    setBusy(true); setMsg('')
    try {
      // Последовательная постановка: problems — рабочая очередь СА
      for (const p of data?.problems ?? []) {
        await reindexMaterial(p.id).catch(() => undefined)
      }
      setMsg('Переиндексация поставлена в очередь; прогресс — по кнопке «Обновить»')
      load()
    } finally {
      setBusy(false)
    }
  }

  if (error) return <Err>{error}</Err>
  if (!data) return <Loading />
  const c = data.counts ?? {}
  const total = Object.values(c).reduce((a, b) => a + b, 0)

  return (
    <div>
      <div className="statgrid">
        <Stat label="Материалов всего" value={total} />
        <Stat label="Проиндексировано" value={c.indexed ?? 0} tone="ok" />
        <Stat label="В очереди" value={c.pending ?? 0} tone={c.pending ? 'warn' : undefined} />
        <Stat label="Ошибки" value={c.error ?? 0} tone={c.error ? 'err' : undefined} />
        <Stat label="Не индексируется" value={c.none ?? 0} />
        <Stat label="Чанков в базе" value={data.total_chunks} />
      </div>
      <Ok>{msg}</Ok>

      <div className="panel">
        <div className="toolbar">
          <strong style={{ fontSize: 13 }}>Очередь внимания (в очереди / ошибки)</strong>
          <span className="spacer" />
          <button className="btn small" disabled={busy || !data.problems.length}
                  onClick={() => void reindexAll()}>Переиндексировать все</button>
          <button className="btn small ghost" onClick={load}>Обновить</button>
        </div>
        {data.problems.length === 0 ? (
          <Empty>Проблем нет: конвейер в порядке</Empty>
        ) : (
          <table className="tbl">
            <thead>
              <tr><th>Материал</th><th>Состояние</th><th>Изменён</th><th></th></tr>
            </thead>
            <tbody>
              {data.problems.map((p) => (
                <tr key={p.id}>
                  <td className="mname">
                    <a href="#" onClick={(e) => { e.preventDefault(); onOpenMaterial(p.id) }}>{p.name}</a>
                    {p.stale && <span className="meta"> · устарел</span>}
                  </td>
                  <td className="nowrap" style={{ color: p.state === 'error' ? 'var(--danger)' : 'var(--warnfg)' }}>
                    {STATE_RU[p.state] ?? p.state}
                  </td>
                  <td className="nowrap">{fmtDate(p.updated_at)}</td>
                  <td>
                    <button className="btn small" disabled={busy}
                            onClick={() => void reindexMaterial(p.id).then(load)}>
                      Переиндексировать
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="note">Отставшие задачи поднимает ежечасная свёрка (reconcile, RAG_DESIGN §5).</p>
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'ok' | 'warn' | 'err' }) {
  return (
    <div className="panel stat">
      <div className="statnum" style={tone ? { color: TONE_COLOR[tone] } : undefined}>{value}</div>
      <div className="statlbl">{label}</div>
    </div>
  )
}

// ---------------------------------------------------------------- конфиг групп
function ConfigTab() {
  const [selected, setSelected] = useState<GroupNode | null>(null)
  const [cfg, setCfg] = useState<RagConfigOut | null>(null)
  const [chunker, setChunker] = useState('recursive')
  const [params, setParams] = useState('{}')
  const [enabled, setEnabled] = useState(true)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  // Дерево групп — TanStack Query (кэш с другими экранами)
  const treeQ = useQuery({ queryKey: ['groups'], queryFn: getGroupTree })
  const tree = treeQ.data ?? []

  const loadCfg = useCallback((gid: string) => {
    getRagGroupConfig(gid)
      .then((c) => {
        setCfg(c)
        setChunker(c.own?.chunker ?? c.effective?.chunker ?? 'recursive')
        setParams(JSON.stringify(c.own?.params ?? c.effective?.params ?? {}, null, 2))
        setEnabled(c.own?.enabled ?? c.effective?.enabled ?? true)
        setError('')
      })
      .catch((e) => setError(errText(e)))
  }, [])

  useEffect(() => {
    if (selected) loadCfg(selected.id)
    else setCfg(null)
  }, [selected, loadCfg])

  const save = async () => {
    if (!selected) return
    setBusy(true); setMsg(''); setError('')
    try {
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(params) as Record<string, unknown>
      } catch {
        throw new Error('params — не корректный JSON')
      }
      await updateRagGroupConfig(selected.id, { chunker, params: parsed, enabled })
      setMsg(`Настройка группы «${selected.name}» сохранена (аудит: rag.group_config)`)
      loadCfg(selected.id)
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!selected) return
    setBusy(true); setMsg(''); setError('')
    try {
      await deleteRagGroupConfig(selected.id)
      setMsg('Явная настройка снята — подгруппы наследуют предков')
      loadCfg(selected.id)
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const reindexSubtree = async () => {
    if (!selected) return
    setBusy(true); setMsg(''); setError('')
    try {
      await reindexGroupSubtree(selected.id)
      setMsg('Переиндексация поддерева поставлена в очередь (см. «Статус индексации»)')
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  // Плоский список для select: вложенность — префиксом «— »
  const flat: { id: string; label: string }[] = []
  const walk = (nodes: GroupNode[], depth: number) => {
    for (const n of nodes) {
      flat.push({ id: n.id, label: `${'— '.repeat(depth)}${n.name}` })
      if (n.children?.length) walk(n.children, depth + 1)
    }
  }
  walk(tree, 0)

  const inherited = cfg?.inherit_from != null

  return (
    <div className="browser">
      <aside className="side-in-panel">
        <h4>Группа</h4>
        <select size={15} style={{ width: '100%' }} value={selected?.id ?? ''}
                onChange={(e) => {
                  const g = flat.find((x) => x.id === e.target.value)
                  setSelected(g ? { id: g.id, name: g.label.replaceAll('— ', ''), parent_id: null, path: '' } : null)
                }}>
          {flat.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
        </select>
      </aside>
      <section className="browser-list">
        <Err>{error}</Err>
        <Ok>{msg}</Ok>
        {!selected ? (
          <Empty>Выберите группу слева</Empty>
        ) : !cfg ? (
          <Loading />
        ) : (
          <div className="panel">
            <div className="toolbar">
              <strong style={{ fontSize: 13 }}>Конфигурация чанкования: {selected.name}</strong>
              <span className="spacer" />
              {inherited && <span className="meta">Наследует настройку группы {cfg.inherit_from}</span>}
            </div>

            {cfg.own ? (
              <p className="note">У группы есть явная настройка (чанкер «{cfg.own.chunker}»).</p>
            ) : (
              <p className="note">
                Явной настройки нет — действует{' '}
                {cfg.effective
                  ? <>унаследованный чанкер «{cfg.effective.chunker}»</>
                  : <>системный дефолт (ключ rag.default_chunker в «Параметрах системы»)</>}.
              </p>
            )}

            <div className="formrow">
              <label className="srchfld">Чанкер:
                <select value={chunker} onChange={(e) => setChunker(e.target.value)}>
                  {cfg.chunkers.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
              <label className="checkrow">
                <input type="checkbox" checked={enabled}
                       onChange={(e) => setEnabled(e.target.checked)} />
                Индексировать это поддерево (enabled)
              </label>
            </div>
            <div className="formrow">
              <label className="srchfld" style={{ alignItems: 'flex-start' }}>
                Параметры (JSON):
                <textarea value={params} rows={6} style={{ width: 380, fontFamily: 'monospace', fontSize: 12 }}
                          onChange={(e) => setParams(e.target.value)} />
              </label>
            </div>
            <div className="btnrow">
              <button className="btn primary" disabled={busy} onClick={() => void save()}>Сохранить</button>
              {cfg.own && (
                <button className="btn ghost" disabled={busy} onClick={() => void remove()}>Снять явную настройку</button>
              )}
              <button className="btn" disabled={busy} onClick={() => void reindexSubtree()}
                      title="Переиндексировать все материалы поддерева этой группы">Переиндексировать поддерево</button>
            </div>
            <p className="note">
              Настройка группы распространяется на подгруппы без собственной строки (§3.2);
              снятие настройки возвращает наследование. После сохранения запустите
              переиндексацию поддерева — либо дождитесь ежечасной свёрки.
            </p>
          </div>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------- провайдер
function ConnectionTab() {
  const [result, setResult] = useState<{ model: string; dim: number } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const test = () => {
    setBusy(true); setError(''); setResult(null)
    testRagConnection()
      .then((r) => setResult(r))
      .catch((e) => setError(errText(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="panel">
      <p className="note">
        Провайдер эмбеддингов настраивается окружением (12-Factor): KB_RAG_EMBEDDING_BASE_URL,
        KB_RAG_EMBEDDING_API_KEY, KB_RAG_EMBEDDING_MODEL, KB_RAG_EMBEDDING_DIM.
        Размерность фиксируется миграцией (столбец vector(dim)); смена модели/размерности
        требует миграции и полного переиндекса (RAG_DESIGN §2, §9-1).
      </p>
      <div className="btnrow">
        <button className="btn primary" disabled={busy} onClick={test}>
          {busy ? 'Проверка…' : 'Проверить соединение'}
        </button>
      </div>
      <Err>{error}</Err>
      {result && (
        <Ok>Соединение установлено: модель «{result.model}», размерность {result.dim}</Ok>
      )}
    </div>
  )
}
