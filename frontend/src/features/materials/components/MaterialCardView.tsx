// Корневой вид карточки материала (US-037): двухпанельная компоновка
// (содержание + боковая колонка). Реорганизация frontend: вся логика — в
// useMaterialCard, боковая колонка — CardSidebar, диалоги — CardDialogs.
// Маршрут /materials/:id (react-router); PermissionsEditor монтирует App.
import { StatusBadge } from '../../../shared/ui/index'
import { STATUS_RU, fmtDate } from '../../../shared/lib/dicts'
import { useMaterialCard } from '../hooks/useMaterialCard'
import { CardSidebar } from './CardSidebar'
import { ChildDialog, CopyDialog, MasterDialog, MoveDialog } from './CardDialogs'
import { Err } from '../../../shared/ui/index'

export default function MaterialCardView({ materialId, onSaved, onClosed, onOpenCard }: {
  materialId: string
  onSaved: () => void
  onClosed: () => void
  onOpenCard?: (materialId: string) => void // этап 7: переход по ссылкам мастер/подчинённые (FR-126)
}) {
  const c = useMaterialCard(materialId, {
    onSaved,
    onClosed,
  })
  const card = c.card
  if (c.error && !card) {
    return (
      <div>
        <Err>{c.error}</Err>
        <button className="btn ghost" onClick={onClosed}>← К списку</button>
      </div>
    )
  }
  if (!card) return <div className="spin">Загрузка…</div>

  const p = card.permissions ?? {}

  return (
    <div>
      <div className="btnrow">
        <button className="btn ghost small" onClick={onClosed}>← К списку</button>
      </div>

      <div className="panel">
        <div className="cardhead">
          <StatusBadge status={card.status} />
          <h2>{card.name}</h2>
          <div className="sub">{STATUS_RU[card.status]} · версия {card.version}</div>
        </div>
        <Err>{c.error}</Err>

        <div className="cardgrid">
          <div className="cmain">
            <table className="kv">
              <tbody>
                <tr><td className="k">Тип</td><td>{card.type_name ?? card.type_id}</td></tr>
                <tr><td className="k">Автор</td><td className="mono">{card.author_id.slice(0, 8)}…</td></tr>
                <tr><td className="k">Изменён</td><td>{fmtDate(card.updated_at)}</td></tr>
                <tr><td className="k">Опубликован</td><td>{fmtDate(card.published_at)}</td></tr>
              </tbody>
            </table>

            {/* Этап 7 (FR-126): ссылка на мастера или список подчинённых */}
            <div className="fld">
              <label>Мастер / подчинённые</label>
              {card.master_id ? (
                <div>
                  Мастер:{' '}
                  {card.master ? (
                    <a href="#" onClick={(e) => { e.preventDefault(); onOpenCard?.(card.master!.id) }}>
                      {card.master.name}
                    </a>
                  ) : card.master_id}{' '}
                  <small className="note">({STATUS_RU[card.master?.status ?? card.status]})</small>
                  {p.edit && card.status !== 'archived' && (
                    <button className="btn small" onClick={c.detachMasterAction} style={{ marginLeft: 12 }}>
                      Отвязать от мастера
                    </button>
                  )}
                </div>
              ) : (
                <span className="note">Самостоятельный материал (мастера нет)</span>
              )}
              {card.children.length > 0 && (
                <ul className="children-list">
                  {card.children.map((ch) => (
                    <li key={ch.id}>
                      <a href="#" onClick={(e) => { e.preventDefault(); onOpenCard?.(ch.id) }}>{ch.name}</a>{' '}
                      <small className="note">{STATUS_RU[ch.status]}</small>
                    </li>
                  ))}
                </ul>
              )}
              {card.children.length === 0 && !card.master_id && (
                <span className="note">Подчинённых нет</span>
              )}
            </div>

            {p.edit ? (
              c.editing ? (
                <div>
                  <label className="field">
                    <span className="lbl">Название</span>
                    <input value={c.name} onChange={(e) => c.setName(e.target.value)} />
                  </label>
                  <label className="field">
                    <span className="lbl">Текст (Markdown)</span>
                    <textarea value={c.text} onChange={(e) => c.setText(e.target.value)} rows={10} />
                  </label>
                  <div className="btnrow">
                    <button className="btn primary" onClick={c.save} disabled={c.saving}>
                      {c.saving ? 'Сохранение…' : 'Сохранить'}
                    </button>
                    <button
                      className="btn ghost"
                      onClick={() => { c.setEditing(false); c.setName(card.name); c.setText(card.text_content ?? '') }}
                    >
                      Отмена
                    </button>
                  </div>
                </div>
              ) : (
                <div className="btnrow">
                  <button className="btn primary" onClick={() => c.setEditing(true)}>Редактировать</button>
                  {p.delete && (card.status === 'draft' || card.status === 'in_review') && (
                    <button className="btn danger" onClick={c.remove}>Удалить</button>
                  )}
                </div>
              )
            ) : (
              <p className="note">Редактирование недоступно (нет права «Редактирование»)</p>
            )}

            {/* Содержание */}
            {!c.editing && card.text_content && (
              <div className="fld">
                <label>Содержание</label>
                <div className="content-text">{card.text_content}</div>
              </div>
            )}

            {/* Атрибуты */}
            <div className="fld">
              <label>Атрибуты</label>
              {card.attributes.length === 0 ? (
                <span className="note">Не заполнены</span>
              ) : (
                <table className="kv">
                  <tbody>
                    {card.attributes.map((a) => (
                      <tr key={a.attribute_id}>
                        <td className="k">
                          {a.name}
                          {a.is_required && <span className="req"> *</span>}
                          {a.readonly && <small className="note"> (только чтение)</small>}
                        </td>
                        <td>{a.values.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Этап 7: комментарии (US-038, FR-096–098) */}
            <div className="fld">
              <label>Комментарии</label>
              {c.comments.length === 0 && <span className="note">Комментариев нет</span>}
              <ul className="comment-list">
                {c.comments.map((cm) => (
                  <li key={cm.id}>
                    <small className="mono">{fmtDate(cm.created_at)}</small>
                    <span className="mono">{cm.author_id.slice(0, 8)}…</span>
                    <span style={{ whiteSpace: 'pre-wrap' }}>{cm.text}</span>
                  </li>
                ))}
              </ul>
              {/* FR-098: добавляют участники процесса (автор + edit/review/publish);
                  право create в карте — не участника; проверка — на сервере */}
              {(p.edit || p.review || p.publish || card.status === 'draft') && (
                <div className="btnrow">
                  <textarea
                    value={c.commentText} onChange={(e) => c.setCommentText(e.target.value)}
                    placeholder="Добавить комментарий…" rows={2} style={{ flex: 1, minWidth: 240 }}
                  />
                  <button className="btn small" onClick={c.addCommentAction} disabled={!c.commentText.trim()}>
                    Отправить
                  </button>
                </div>
              )}
            </div>
          </div>

          <CardSidebar card={c} />
        </div>
      </div>

      {c.dialog === 'child' && <ChildDialog card={c} />}
      {c.dialog === 'copy' && <CopyDialog card={c} />}
      {c.dialog === 'move' && <MoveDialog card={c} />}
      {c.dialog === 'master' && <MasterDialog card={c} />}
    </div>
  )
}
