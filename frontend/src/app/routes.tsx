import { Navigate, createBrowserRouter } from 'react-router-dom'

import { AppShell } from '@/components/layout/AppShell'
import { AssistantPage } from '@/features/assistant/AssistantPage'
import { InsightsListPage } from '@/features/insights/InsightsListPage'
import { InsightDetailPage } from '@/features/insights/InsightDetailPage'
import { RequestsListPage } from '@/features/requests/RequestsListPage'
import { RequestDetailPage } from '@/features/requests/RequestDetailPage'
import { NewRequestPage } from '@/features/requests/NewRequestPage'
import { PreferencesPage } from '@/features/preferences/PreferencesPage'
import { NotFoundPage } from '@/features/NotFoundPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/assistant" replace /> },
      { path: 'assistant', element: <AssistantPage /> },
      { path: 'insights', element: <InsightsListPage /> },
      { path: 'insights/:insightId', element: <InsightDetailPage /> },
      { path: 'requests', element: <RequestsListPage /> },
      { path: 'requests/new', element: <NewRequestPage /> },
      { path: 'requests/:requestId', element: <RequestDetailPage /> },
      { path: 'preferences', element: <PreferencesPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
