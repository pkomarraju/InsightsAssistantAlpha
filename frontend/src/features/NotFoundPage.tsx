import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'

import { EmptyState } from '@/components/states/EmptyState'

export function NotFoundPage() {
  return (
    <EmptyState icon={Compass} title="Page not found" description="The page you're looking for doesn't exist.">
      <Link to="/assistant" className="mt-2 text-sm font-medium text-accent hover:underline">
        Go to Assistant
      </Link>
    </EmptyState>
  )
}
