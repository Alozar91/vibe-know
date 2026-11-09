// Этап 1: каркас без функциональности (план этапа 1).
// Аутентификация (US-001) и интерфейс подключаются на этапах 1–2.
export default function App() {
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', margin: '2rem' }}>
      <h1>Корпоративная база знаний</h1>
      <p>Каркас веб-клиента (этап 1). Функциональность подключается по этапам 2–10.</p>
      <button onClick={async () => {
        const r = await fetch('/api/v1/materials')
        const j = await r.json()
        alert(JSON.stringify(j))
      }}>
        Проверить API
      </button>
    </main>
  )
}
