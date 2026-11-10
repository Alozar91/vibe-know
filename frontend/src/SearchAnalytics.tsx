// Аналитика поиска (US-051, FR-127): простые списки на MVP — только СА.
import { useEffect, useState } from 'react'
import { api } from './auth'

interface Analytics {
  top_queries: { query: string; count: number; total_results: number }[]
  zero_result_queries: { query: string; count: number }[]
  ctr: { opens: number; searches: number; ratio: number }
  text_coverage: { with_text: number; total: number; ratio: number }
}

export default function SearchAnalytics() {
  const [data, setData] = useState<Analytics | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Analytics>('/analytics/search')
      .then(setData)
      .catch((e) => setError(e.detail ?? String(e)))
  }, [])

  if (error) return <div><h2>Аналитика поиска</h2><p style={{ color: '#b00' }}>{error}</p></div>
  if (!data) return <div><h2>Аналитика поиска</h2><p>Загрузка…</p></div>

  return (
    <div>
      <h2>Аналитика поиска</h2>
      <p style={{ color: '#555' }}>Персональные данные не используются (FR-127).</p>

      <h3>Популярные запросы</h3>
      {data.top_queries.length === 0 && <p style={{ color: '#777' }}>Пока нет запросов</p>}
      <table style={{ borderCollapse: 'collapse' }}>
        <tbody>
          {data.top_queries.map((x) => (
            <tr key={x.query}>
              <td style={{ padding: '2px 12px 2px 0' }}>{x.query}</td>
              <td style={{ padding: '2px 12px 2px 0' }}>{x.count} раз(а)</td>
              <td style={{ color: '#777' }}>всего результатов: {x.total_results}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Запросы без результатов</h3>
      {data.zero_result_queries.length === 0 && <p style={{ color: '#777' }}>Нет</p>}
      <ul>
        {data.zero_result_queries.map((x) => (
          <li key={x.query}>{x.query} — {x.count} раз(а)</li>
        ))}
      </ul>

      <h3>CTR открытия материала из выдачи</h3>
      <p>
        {data.ctr.opens} открытий / {data.ctr.searches} запросов ={' '}
        <strong>{(data.ctr.ratio * 100).toFixed(1)}%</strong>
      </p>

      <h3>Доля материалов с текстовым представлением</h3>
      <p>
        {data.text_coverage.with_text} из {data.text_coverage.total} ={' '}
        <strong>{(data.text_coverage.ratio * 100).toFixed(1)}%</strong>{' '}
        <small style={{ color: '#777' }}>(покрытие поиска текстом — ключевой риск качества, 9.2)</small>
      </p>
    </div>
  )
}
