// Аналитика поиска (US-051, FR-127): простые списки на MVP — только СА.
// Реорганизация frontend: запрос — через src/api/search.
import { useEffect, useState } from 'react'
import { getSearchAnalytics } from '../../../api/search'
import { errText } from '../../../shared/lib/dicts'
import { Empty, Err, Loading } from '../../../shared/ui/index'

export default function SearchAnalytics() {
  const [data, setData] = useState<Awaited<ReturnType<typeof getSearchAnalytics>> | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getSearchAnalytics()
      .then(setData)
      .catch((e) => setError(errText(e)))
  }, [])

  if (error) return <div><div className="pagehead"><h2>Аналитика поиска</h2></div><Err>{error}</Err></div>
  if (!data) return <div><div className="pagehead"><h2>Аналитика поиска</h2></div><Loading /></div>

  return (
    <div>
      <div className="pagehead"><h2>Аналитика поиска</h2></div>
      <p className="note">Персональные данные не используются (FR-127).</p>

      <div className="statgrid">
        <div className="panel stat">
          <div className="statnum">{data.ctr.ratio ? (data.ctr.ratio * 100).toFixed(1) + '%' : '—'}</div>
          <div className="statlbl">CTR открытия из выдачи</div>
          <div className="note">{data.ctr.opens} открытий / {data.ctr.searches} запросов</div>
        </div>
        <div className="panel stat">
          <div className="statnum">
            {data.text_coverage.total ? (data.text_coverage.ratio * 100).toFixed(1) + '%' : '—'}
          </div>
          <div className="statlbl">Покрытие текстом</div>
          <div className="note">{data.text_coverage.with_text} из {data.text_coverage.total} (9.2)</div>
        </div>
      </div>

      <div className="panel">
        <div className="toolbar"><strong style={{ fontSize: 13 }}>Популярные запросы</strong></div>
        {data.top_queries.length === 0 ? <Empty>Пока нет запросов</Empty> : (
          <table className="tbl">
            <tbody>
              {data.top_queries.map((x) => (
                <tr key={x.query}>
                  <td className="mname">{x.query}</td>
                  <td>{x.count} раз(а)</td>
                  <td className="note">всего результатов: {x.total_results}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <div className="toolbar"><strong style={{ fontSize: 13 }}>Запросы без результатов</strong></div>
        {data.zero_result_queries.length === 0 ? <Empty>Нет</Empty> : (
          <ul className="plainlist">
            {data.zero_result_queries.map((x) => (
              <li key={x.query}>{x.query} — {x.count} раз(а)</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
