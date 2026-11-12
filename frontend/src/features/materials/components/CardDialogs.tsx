// Диалоги карточки (этап 7): подчинённый (US-024/025), копия (US-028),
// перемещение (US-027), смена мастера (US-026). Только JSX — логика в хуке.
import { STATUS_RU } from '../../../shared/lib/dicts'
import type { GroupNode, Material } from '../../../shared/types'
import type { useMaterialCard } from '../hooks/useMaterialCard'

type Card = ReturnType<typeof useMaterialCard>

/** Общая обёртка диалогов карточки: заголовок + кнопка «Отмена». */
function DialogShell({ title, onClose, children }: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div className="dialog">
      <h4>{title}</h4>
      {children}
      <div className="btnrow">
        <button className="btn ghost" onClick={onClose}>Отмена</button>
      </div>
    </div>
  )
}

/** Выбор целевой группы (общий для child/copy/move). */
function GroupSelect({ card, onChange }: {
  card: Card
  onChange: (id: string) => void
}) {
  return (
    <label className="field">
      <span className="lbl">Целевая группа</span>
      <select value={card.targetGroup} onChange={(e) => onChange(e.target.value)}>
        <option value="">— выберите группу —</option>
        {card.flatForSelect(card.groups as GroupNode[]).map(({ g, depth }: { g: GroupNode; depth: number }) => (
          <option key={g.id} value={g.id}>{'  '.repeat(depth)}{g.name}</option>
        ))}
      </select>
    </label>
  )
}

export function ChildDialog({ card }: { card: Card }) {
  return (
    <DialogShell title="Создать подчинённый материал" onClose={() => card.setDialog(null)}>
      <label className="field">
        <span className="lbl">Вид</span>
        <select value={card.childKind} onChange={(e) => {
          const kind = e.target.value as 'adaptation' | 'translation'
          card.setChildKind(kind)
          card.setChildName(kind === 'translation'
            ? `${card.card!.name} (Перевод, …)`
            : `${card.card!.name} Адаптация`)
        }}>
          <option value="adaptation">Адаптация</option>
          <option value="translation">Перевод</option>
        </select>
      </label>
      {card.childKind === 'translation' && (
        <label className="field">
          <span className="lbl">Язык перевода (обязателен — US-025 A1)</span>
          <select value={card.childLang} onChange={(e) => card.setChildLang(e.target.value)}>
            <option value="">— выберите язык —</option>
            {card.langOptions.map((v: { id: string; value: string }) => (
              <option key={v.id} value={v.id}>{v.value}</option>
            ))}
          </select>
          {card.langOptions.length === 0 && (
            <div className="alert err"> Справочник «Язык» не заведён (СА: атрибуты → справочники)</div>
          )}
        </label>
      )}
      <label className="field">
        <span className="lbl">Имя (по умолчанию — FR-035)</span>
        <input value={card.childName} onChange={(e) => card.setChildName(e.target.value)} />
      </label>
      <GroupSelect card={card} onChange={card.setTargetGroup} />
      <div className="btnrow">
        <button
          className="btn primary"
          onClick={card.createChildSubmit}
          disabled={card.busy || !card.targetGroup || (card.childKind === 'translation' && !card.childLang.trim())}
        >
          Создать
        </button>
      </div>
    </DialogShell>
  )
}

export function CopyDialog({ card }: { card: Card }) {
  return (
    <DialogShell title="Копировать материал" onClose={() => card.setDialog(null)}>
      <p className="note">Имя копии: {card.childName} (счётчик при конфликте — FR-092)</p>
      <GroupSelect card={card} onChange={card.setTargetGroup} />
      <div className="btnrow">
        <button className="btn primary" onClick={card.doCopy} disabled={card.busy || !card.targetGroup}>
          Копировать
        </button>
      </div>
    </DialogShell>
  )
}

export function MoveDialog({ card }: { card: Card }) {
  return (
    <DialogShell title="Переместить материал" onClose={() => card.setDialog(null)}>
      <p className="note">
        Требуется право «Перемещение» в обеих группах. При конфликте имени операция будет
        отклонена — переименуйте материал заранее (FR-037).
      </p>
      <GroupSelect card={card} onChange={card.setTargetGroup} />
      <div className="btnrow">
        <button className="btn primary" onClick={card.doMove} disabled={card.busy || !card.targetGroup}>
          Переместить
        </button>
      </div>
    </DialogShell>
  )
}

export function MasterDialog({ card }: { card: Card }) {
  return (
    <DialogShell title="Сменить мастера" onClose={() => card.setDialog(null)}>
      <label className="field">
        <span className="lbl">Новый мастер (approved/published, FR-036)</span>
        <input value={card.masterName} onChange={(e) => card.searchMasters(e.target.value)}
               placeholder="Начните вводить название" />
      </label>
      <ul className="master-options">
        {card.masterOptions.map((m: Material) => (
          <li key={m.id}>
            <button className="btn small" onClick={() => card.changeMaster(m.id)} disabled={card.busy}>
              {m.name}
            </button>
            <small className="note"> {STATUS_RU[m.status]}</small>
          </li>
        ))}
      </ul>
    </DialogShell>
  )
}
