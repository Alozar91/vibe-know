import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.tsx'

// Интерфейс на русском языке (NFR-018); дизайн — отдельный трек (16.1-33)
// Реорганизация frontend: BrowserRouter (deep links, SPA-fallback nginx)
// + QueryClientProvider (кэш/инвалидация вместо ручных refreshToken-пропсов).
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
