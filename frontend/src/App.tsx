import { RouterProvider } from 'react-router-dom'

import { PreferencesProvider } from '@/app/PreferencesProvider'
import { RepositoriesProvider } from '@/app/RepositoriesProvider'
import { ToastProvider } from '@/app/ToastProvider'
import { TooltipProvider } from '@/components/ui/tooltip'
import { router } from '@/app/routes'

function App() {
  return (
    <RepositoriesProvider>
      <PreferencesProvider>
        <TooltipProvider delayDuration={200}>
          <ToastProvider>
            <RouterProvider router={router} />
          </ToastProvider>
        </TooltipProvider>
      </PreferencesProvider>
    </RepositoriesProvider>
  )
}

export default App
