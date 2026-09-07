import { useNavigate } from 'react-router-dom'
import { LogOut, Menu, Settings } from 'lucide-react'

import { usePreferences } from '@/app/PreferencesProvider'
import { initials } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

interface HeaderProps {
  onOpenMobileNav: () => void
}

export function Header({ onOpenMobileNav }: HeaderProps) {
  const navigate = useNavigate()
  const { preferences } = usePreferences()

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface-raised px-4 lg:px-6">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={onOpenMobileNav}
          aria-label="Open navigation"
        >
          <Menu className="size-5" />
        </Button>
        <span className="text-sm font-medium text-ink-muted">Relationship Banking</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="outline" className="hidden sm:inline-flex">
              Synthetic demo data
            </Badge>
          </TooltipTrigger>
          <TooltipContent>
            Company names are real; all relationship, financial, and risk data shown is fictional demo data.
          </TooltipContent>
        </Tooltip>
      </div>

      {preferences ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-hover"
            >
              <span className="flex size-7 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                {initials(preferences.displayName)}
              </span>
              <span className="hidden text-ink sm:inline">{preferences.displayName}</span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{preferences.role}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => navigate('/preferences')}>
              <Settings className="size-4" />
              Preferences
            </DropdownMenuItem>
            <DropdownMenuItem disabled>
              <LogOut className="size-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <Skeleton className="size-7 rounded-full" />
      )}
    </header>
  )
}
