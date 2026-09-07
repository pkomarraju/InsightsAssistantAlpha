import { useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { LayoutDashboard, Lightbulb, ListChecks, MessagesSquare, Settings, X } from 'lucide-react'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

const NAV_ITEMS = [
  { to: '/assistant', label: 'Assistant', icon: MessagesSquare },
  { to: '/insights', label: 'Insights', icon: Lightbulb },
  { to: '/requests', label: 'Requests', icon: ListChecks },
  { to: '/preferences', label: 'Preferences', icon: Settings },
] as const

interface SidebarProps {
  mobileOpen: boolean
  onCloseMobile: () => void
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <div className="flex h-14 items-center gap-2 px-5">
        <div className="flex size-7 items-center justify-center rounded-md bg-accent text-white">
          <LayoutDashboard className="size-4" />
        </div>
        <span className="text-sm font-semibold tracking-tight text-ink">Insights Assistant</span>
      </div>
      <nav className="flex flex-col gap-0.5 px-3 py-2" aria-label="Primary">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-accent-soft text-accent'
                  : 'text-ink-muted hover:bg-surface-hover hover:text-ink',
              )
            }
          >
            <Icon className="size-4" />
            {label}
          </NavLink>
        ))}
      </nav>
    </>
  )
}

export function Sidebar({ mobileOpen, onCloseMobile }: SidebarProps) {
  // Radix's default close-focus restoration doesn't reliably find the
  // hamburger button here (it lives in a sibling component, Header, not a
  // DialogPrimitive.Trigger), so capture it explicitly whenever the drawer
  // opens and hand it back via onCloseAutoFocus.
  const triggerElementRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (mobileOpen) triggerElementRef.current = document.activeElement as HTMLElement | null
  }, [mobileOpen])

  return (
    <>
      <aside className="hidden w-60 shrink-0 border-r border-border bg-surface-raised lg:flex lg:flex-col">
        <SidebarContent />
      </aside>

      {/* Mobile nav uses Radix Dialog (not the shared centered Dialog) so it
          gets focus trapping and Escape-to-close for free, styled as a
          left-anchored panel instead of a centered modal. */}
      <DialogPrimitive.Root open={mobileOpen} onOpenChange={(open) => !open && onCloseMobile()}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/40 lg:hidden" />
          <DialogPrimitive.Content
            className="fixed inset-y-0 left-0 z-40 flex h-full w-64 flex-col bg-surface-raised shadow-lg outline-none lg:hidden"
            aria-describedby={undefined}
            onCloseAutoFocus={(e) => {
              e.preventDefault()
              triggerElementRef.current?.focus()
            }}
          >
            <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
            <div className="flex justify-end p-2">
              <DialogPrimitive.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close navigation">
                  <X className="size-4" />
                </Button>
              </DialogPrimitive.Close>
            </div>
            <SidebarContent onNavigate={onCloseMobile} />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </>
  )
}
