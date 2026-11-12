// Боковая колонка карточки: действия жизненного цикла (US-015–021), связи и
// копирование (этап 7), файл/конвейер (US-011–014), версии (US-041/042),
// журнал статусов (FR-075), права пользователя (FR-129). Только JSX — логика в хуке.
import { PDF_RU, PERMISSIONS_RU, SCAN_RU, STATUS_RU, fmtDate } from '../../../shared/lib/dicts'
import type { useMaterialCard } from '../hooks/useMaterialCard'

type Card = ReturnType<typeof useMaterialCard>

export function CardSidebar({ card: c }: { card: Card }) {
  const p = c.card!.permissions ?? {}

  return (
    <div className="cside">
      {/* Этап 5: действия жизненного цикла по матрице (US-015–021) */}
      <div className="fld">
        <label>Действия жизненного цикла</label>
        {c.transitions.length === 0 && (
          <span className="note">Нет доступных переходов из статуса «{STATUS_RU[c.card!.status]}»</span>
        )}
        <div className="btnrow">
          {c.transitions.map((t) => (
            <button
              key={t.id}
              className={`btn small ${t.allowed ? 'primary' : 'ghost'}`}
              onClick={() => c.doTransition(t)}
              disabled={!t.allowed}
              title={t.allowed
                ? 'Права перехода: ' + t.permissions.map((x) => PERMISSIONS_RU[x] ?? x).join(', ')
                : 'Нет права на этот переход'}
            >
              → {STATUS_RU[t.to_status]}
            </button>
          ))}
        </div>
      </div>

      {/* Действия этапа 7 */}
      <div className="fld">
        <label>Связи и копирование</label>
        <div className="btnrow">
          {p.create && <button className="btn small" onClick={c.openChildDialog}>Подчинённый</button>}
          {p.copy && <button className="btn small" onClick={c.openCopyDialog}>Копировать</button>}
          {p.move && c.card!.children.length === 0 && c.card!.status !== 'archived' && (
            <button className="btn small" onClick={c.openMoveDialog}>Переместить</button>
          )}
          {p.edit && c.card!.master_id && c.card!.status !== 'archived' && (
            <button className="btn small" onClick={c.openMasterDialog}>Сменить мастера</button>
          )}
        </div>
      </div>

      {/* Этап 6: файл, конвейер (US-011/012/013), скачивание (US-014) */}
      <div className="fld">
        <label>Файл</label>
        {!c.fileState?.file_id && <span className="note">Файл не загружен</span>}
        {c.fileState?.file_id && (
          <>
            <table className="kv">
              <tbody>
                <tr><td className="k">Имя</td><td>{c.fileState.filename}</td></tr>
                <tr><td className="k">Тип</td><td>{c.fileState.mime_type} · {Math.round((c.fileState.size_bytes ?? 0) / 1024)} КБ</td></tr>
                <tr><td className="k">Антивирус</td><td>{c.fileState.scan_state && SCAN_RU[c.fileState.scan_state]}</td></tr>
                <tr><td className="k">PDF</td><td>{c.fileState.pdf_state && PDF_RU[c.fileState.pdf_state]}</td></tr>
              </tbody>
            </table>
            <div className="btnrow">
              {c.fileState.scan_state === 'ready' && p.download && (
                <button className="btn small" onClick={() => c.download('file')}>Скачать файл</button>
              )}
              {c.fileState.pdf_state === 'ready_pdf' && (
                <button className="btn small" onClick={() => c.download('pdf')}>PDF</button>
              )}
              {p.download && c.card!.text_content && (
                <button className="btn small" onClick={() => c.download('text.md')}>Текст .md</button>
              )}
            </div>
            {c.fileState.scan_state !== 'ready' && (
              <div className="alert warn">Файл недоступен до завершения проверки (US-011)</div>
            )}
          </>
        )}
        {p.edit && c.card!.status !== 'archived' && (
          <div className="btnrow">
            <input
              type="file" disabled={c.busy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void c.uploadFile(f); e.target.value = '' }}
            />
            {c.busy && <small className="note"> Загрузка…</small>}
          </div>
        )}
        {c.card!.text_out_of_sync && (
          <div className="alert warn">Текстовое представление не синхронизировано с файлом (FR-030)</div>
        )}
      </div>

      {/* Этап 6: версии (US-041/042, FR-145–148) */}
      <div className="fld">
        <label>Версии</label>
        {c.versions.length === 0 && <span className="note">Версий ещё нет</span>}
        <ul className="version-list">
          {c.versions.map((v) => (
            <li key={v.number}>
              <span className="mono">v{v.number}</span>
              <span className="mono">{fmtDate(v.created_at)}</span>
              <button className="btn small" onClick={() => c.showDiff(v.number)}>diff</button>
              {p.edit && c.card!.status !== 'archived' && (
                <button className="btn small" onClick={() => c.restore(v.number)}>Восстановить</button>
              )}
            </li>
          ))}
        </ul>
        {c.diff && (
          <div className="diffbox">
            <b>Сравнение версии {c.diff.number} с предыдущей</b>
            {c.diff.file_changed && <div className="alert warn">Файл изменён в этой версии</div>}
            {c.diff.metadata_changes.length > 0 && (
              <table className="kv">
                <tbody>
                  {c.diff.metadata_changes.map((ch, i) => (
                    <tr key={i}>
                      <td className="k">{ch.field}</td>
                      <td className="old" style={{ paddingRight: 12 }}>{ch.old || '—'}</td>
                      <td className="new">{ch.new || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {c.diff.text_diff.length > 0 && <pre>{c.diff.text_diff.join('\n')}</pre>}
            {!c.diff.file_changed && c.diff.metadata_changes.length === 0 && c.diff.text_diff.length === 0 && (
              <div className="note">Различий нет</div>
            )}
          </div>
        )}
      </div>

      {/* Этап 5: журнал статусов (FR-075) */}
      <div className="fld">
        <label>История статусов</label>
        {c.log.length === 0 && <span className="note">Переходов ещё не было</span>}
        <ul className="pipeline">
          {c.log.map((e, i) => (
            <li key={i}>
              <span className="when">{fmtDate(e.created_at)}</span>
              <span>
                {e.from_status ? `${STATUS_RU[e.from_status]} → ` : ''}
                {STATUS_RU[e.to_status]}
              </span>
              <span className="note">{e.user_display_name}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Права пользователя (FR-129) */}
      <div className="fld">
        <label>Права (ваш доступ)</label>
        <span className="note">
          {Object.entries(p).filter(([, v]) => v).map(([k2]) => PERMISSIONS_RU[k2] ?? k2).join(', ') || 'только просмотр'}
        </span>
      </div>
    </div>
  )
}
