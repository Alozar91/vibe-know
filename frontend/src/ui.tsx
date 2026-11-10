// Общие UI-элементы (modern-ui): бейджи статусов, пагинация, алерты, пустые состояния.
import type { ReactNode } from 'react'

/** Цветной бейдж статуса материала (вместо текста). */
export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge b-${status}`}>{STATUS_RU[status] ?? status}</span>
}

export const STATUS_RU: Record<string, string> = {
  draft: 'Черновик',
  in_review: 'На проверке',
  approved: 'Утверждён',
  published: 'Публикация',
  archived: 'Архив',
}

/** Строка пагинации: «Страница N из M» + кнопки. */
export function Pager({ page, pages, total, onPrev, onNext }: {
  page: number
  pages: number
  total?: number
  onPrev: () => void
  onNext: () => void
}) {
  return (
    <div className="pager">
      <span>
        Страница {page} из {pages}
        {typeof total === 'number' && <> · всего {total}</>}
      </span>
      <span className="spacer" />
      <button className="pg" disabled={page <= 1} onClick={onPrev} title="Предыдущая">‹</button>
      <button className="pg" disabled={page >= pages} onClick={onNext} title="Следующая">›</button>
    </div>
  )
}

export function Err({ children }: { children: ReactNode }) {
  return children ? <div className="alert err">{children}</div> : null
}

export function Ok({ children }: { children: ReactNode }) {
  return children ? <div className="alert ok">{children}</div> : null
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Loading() {
  return <div className="spin">Загрузка…</div>
}
