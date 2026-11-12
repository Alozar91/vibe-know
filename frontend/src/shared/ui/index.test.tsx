// Тесты общих UI-компонентов.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Empty, Err, Loading, Ok, Pager, StatusBadge } from './index'

describe('StatusBadge', () => {
  it('показывает русское название статуса и класс бейджа', () => {
    render(<StatusBadge status="in_review" />)
    const b = screen.getByText('На проверке')
    expect(b.className).toBe('badge b-in_review')
  })

  it('неизвестный статус — показывается как есть', () => {
    render(<StatusBadge status="future_status" />)
    expect(screen.getByText('future_status')).toBeTruthy()
  })
})

describe('Pager', () => {
  it('показывает страницу/всего и блокирует границы', () => {
    render(<Pager page={1} pages={3} total={125} onPrev={() => {}} onNext={() => {}} />)
    expect(screen.getByText(/Страница 1 из 3/)).toBeTruthy()
    expect(screen.getByText(/всего 125/)).toBeTruthy()
    const prev = screen.getByTitle('Предыдущая') as HTMLButtonElement
    const next = screen.getByTitle('Следующая') as HTMLButtonElement
    expect(prev.disabled).toBe(true)
    expect(next.disabled).toBe(false)
  })
})

describe('alerts', () => {
  it('Err/Ok рендерят детей только при непустом содержимом', () => {
    render(<><Err>ошибка</Err><Ok>успех</Ok><Err>{''}</Err></>)
    expect(screen.getByText('ошибка')).toBeTruthy()
    expect(screen.getByText('успех')).toBeTruthy()
  })
  it('Empty/Loading', () => {
    render(<><Empty>пусто</Empty><Loading /></>)
    expect(screen.getByText('пусто')).toBeTruthy()
    expect(screen.getByText('Загрузка…')).toBeTruthy()
  })
})
