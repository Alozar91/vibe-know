// Общие UI-элементы (modern-ui): бейджи статусов, пагинация, алерты, пустые состояния.
import type { ReactNode } from 'react'
import { STATUS_RU } from '../lib/dicts'

/** Цветной бейдж статуса материала (вместо текста). */
export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge b-${status}`}>{STATUS_RU[status as keyof typeof STATUS_RU] ?? status}</span>
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
