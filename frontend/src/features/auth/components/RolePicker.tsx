// Экран выбора роли тестовой регистрации (одноразовый, после первого входа).
// Показывается, только когда флаг включён и ролей у пользователя ещё нет.
// Реорганизация frontend: вынесен из App.tsx.
import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { register } from '../../../shared/auth/auth'

// Оффер тестовой регистрации (НЕ для продуктива): состояние + допустимые роли
interface TestOffer {
  enabled: boolean
  available: boolean
  roles: { id: string; name: string }[]
}

// Подсказки по ролям (сид LLD §2.6; для клонов — общий текст)
const ROLE_HINTS: Record<string, string> = {
  'Читатель': 'Просмотр опубликованных материалов',
  'Автор': 'Создание и редактирование своих материалов',
  'Рецензент': 'Проверка материалов на проверке',
  'Публикатор': 'Публикация и архивация материалов',
  'Системный администратор': 'Полный доступ к системе (стенд: вы сами себе СА)',
}

export default function RolePicker({ onDone }: { onDone: (dismiss?: boolean) => void }) {
  const [offer, setOffer] = useState<TestOffer | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  useEffect(() => {
    api<TestOffer>('/me/test-registration')
      .then(setOffer)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  async function choose(roleId: string) {
    setError('')
    setBusy(roleId)
    try {
      await api('/me/test-registration', { method: 'POST', body: JSON.stringify({ role_id: roleId }) })
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy('')
    }
  }

  if (error) {
    return (
      <div className="rolepick">
        <div className="box">
          <div className="logo mark">БЗ</div>
          <h2>Не удалось загрузить выбор роли</h2>
          <p className="note">{error}</p>
          <button className="btn primary" onClick={() => onDone(true)}>Продолжить без выбора</button>
        </div>
      </div>
    )
  }
  if (!offer) {
    return <div className="rolepick"><div className="box"><p className="spin">Загрузка…</p></div></div>
  }
  if (!offer.available) {
    // Два разных случая: роль уже есть (флаг включён) или флаг выключен —
    // иначе «Роль уже назначена» вводит в заблуждение на стенде без флага.
    const enabled = offer.enabled
    return (
      <div className="rolepick">
        <div className="box">
          <div className="logo mark">БЗ</div>
          <h2>{enabled ? 'Роль уже назначена' : 'Тестовая регистрация отключена'}</h2>
          <p className="note">
            {enabled
              ? 'Выбор роли доступен один раз; смену роли выполняет системный администратор.'
              : 'Выбор роли на этом стенде не включён (флаг KB_TEST_REGISTRATION в deploy/.env). Роль назначит системный администратор, либо включите флаг и перезапустите api.'}
          </p>
          <button className="btn primary" onClick={() => onDone(true)}>Продолжить</button>
        </div>
      </div>
    )
  }
  return (
    <div className="rolepick">
      <div className="box wide">
        <div className="logo mark">БЗ</div>
        <h2>Выберите роль для тестирования</h2>
        <p className="note">
          Тестовый режим: роль определяет права в системе. Выбор одноразовый —
          потом роль может поменять только системный администратор.
        </p>
        {error && <div className="alert err">{error}</div>}
        <div className="rp-grid">
          {offer.roles.map((r) => (
            <button
              key={r.id}
              className="rp-card"
              disabled={!!busy}
              onClick={() => choose(r.id)}
            >
              <div className="rp-name">{r.name}</div>
              <div className="rp-desc">{ROLE_HINTS[r.name] ?? 'Просмотр материалов'}</div>
              <div className="rp-go">{busy === r.id ? 'Назначение…' : 'Выбрать →'}</div>
            </button>
          ))}
        </div>
        <button className="btn ghost small rp-later" onClick={() => onDone(true)}>Пока не выбирать</button>
        <a className="rp-escape" href="" onClick={(e) => { e.preventDefault(); register().catch(console.error) }}>
          Зарегистрировать нового пользователя (тест)
        </a>
      </div>
    </div>
  )
}
