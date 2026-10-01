/**
 * The signed-in chrome: sidebar navigation, header, and the outlet.
 *
 * A sidebar rather than a top bar because the app is data-dense and the
 * navigation set is stable at seven items.
 */

import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { useSession } from '@/auth/SessionContext'
import { fraudApi } from '@/lib/endpoints'

const NAV: { to: string; label: string }[] = [
  { to: '/', label: 'Dashboard' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/budgets', label: 'Budgets' },
  { to: '/fraud', label: 'Fraud alerts' },
  { to: '/loans', label: 'Loans' },
  { to: '/profile', label: 'Profile' },
  { to: '/settings', label: 'Settings' },
]

export default function AppLayout() {
  const { user, signOut } = useSession()
  const [unreadAlerts, setUnreadAlerts] = useState(0)

  /**
   * Badge count.
   *
   * Failures are swallowed deliberately. A badge is decoration; if the count
   * request fails the app should still work, and surfacing an error toast for a
   * failed badge poll would be noise.
   *
   * Only the fraud summary is polled. The unread notification count is not
   * fetched here because nothing in this build renders a notification list or
   * lets a user act on a notification - a badge pointing at a screen that does
   * not exist would be worse than no badge.
   */
  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const alerts = await fraudApi.summary()
        if (cancelled) return
        setUnreadAlerts(alerts.unread)
      } catch {
        // Intentionally ignored; see the comment above.
      }
    }

    void load()
    const timer = window.setInterval(load, 60_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  /**
   * Badge counts by route.
   *
   * Held as a map keyed by path and looked up during render, rather than copying
   * each nav item to attach a badge. `NAV` is module-level and constant, so
   * there is nothing to rebuild per render at all.
   */
  const badges: Record<string, number> = unreadAlerts > 0 ? { '/fraud': unreadAlerts } : {}

  return (
    <div className="flex min-h-screen bg-canvas">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border-subtle bg-surface lg:flex">
        <div className="px-5 py-5">
          <p className="text-lg font-semibold text-text-strong">Finance AI</p>
          <p className="text-xs text-muted">Personal finance</p>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {NAV.map((item) => {
            const badge = badges[item.to]
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `flex items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors ${
                    isActive
                      ? 'bg-accent/15 font-medium text-accent'
                      : 'text-text hover:bg-surface-2'
                  }`
                }
              >
                <span>{item.label}</span>
                {badge ? (
                  <span className="rounded-full bg-danger px-1.5 py-0.5 text-[10px] font-semibold text-white">
                    {badge > 99 ? '99+' : badge}
                  </span>
                ) : null}
              </NavLink>
            )
          })}
        </nav>

        <div className="border-t border-border-subtle p-3">
          <p className="truncate px-2 pb-2 text-sm text-muted">{user?.name ?? user?.email ?? 'Signed in'}</p>
          <button
            type="button"
            onClick={() => void signOut()}
            className="w-full rounded-lg px-2 py-1.5 text-left text-sm text-text hover:bg-surface-2"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border-subtle bg-surface px-5 py-3 lg:hidden">
          <span className="font-semibold text-text-strong">Finance AI</span>
          <button
            type="button"
            onClick={() => void signOut()}
            className="text-sm text-muted"
          >
            Sign out
          </button>
        </header>

        <main className="min-w-0 flex-1 p-5 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
