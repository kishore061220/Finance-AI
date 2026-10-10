/**
 * Application shell and route table.
 *
 * The router splits on session status before rendering any protected screen: an
 * authenticated user landing on /login is redirected to the dashboard, and an
 * anonymous user landing anywhere else is sent to /login. Doing this at the
 * router level rather than per-screen means no screen can forget the check.
 */

import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useSession } from '@/auth/SessionContext'
import AppLayout from '@/components/AppLayout'
import { Spinner } from '@/components/ui'

/**
 * Screens are code-split.
 *
 * The chart-heavy dashboard pulls in Recharts, which is a large dependency, and
 * nothing else does. Splitting the routes keeps that weight out of the bundle a
 * first-time visitor downloads just to see the login screen.
 */
const DashboardPage = lazy(async () => import('@/pages/DashboardPage'))
const TransactionsPage = lazy(async () => import('@/pages/TransactionsPage'))
const BudgetsPage = lazy(async () => import('@/pages/BudgetsPage'))
const FraudPage = lazy(async () => import('@/pages/FraudPage'))
const LoansPage = lazy(async () => import('@/pages/LoansPage'))
const ReportsPage = lazy(async () => import('@/pages/ReportsPage'))
const FamilyPage = lazy(async () => import('@/pages/FamilyPage'))
const AssistantPage = lazy(async () => import('@/pages/AssistantPage'))
const ProfilePage = lazy(async () => import('@/pages/ProfilePage'))
const SettingsPage = lazy(async () => import('@/pages/SettingsPage'))
const LoginPage = lazy(async () => import('@/pages/LoginPage'))
const NotFoundPage = lazy(async () => import('@/pages/NotFoundPage'))

function FullScreenLoader({ label }: { label: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas">
      <Spinner label={label} />
    </div>
  )
}

export default function App() {
  const { status } = useSession()

  if (status === 'loading') {
    return <FullScreenLoader label="Restoring your session" />
  }

  return (
    <Suspense fallback={<FullScreenLoader label="Loading" />}>
      <Routes>
        <Route
          path="/login"
          element={status === 'authenticated' ? <Navigate to="/" replace /> : <LoginPage />}
        />
        <Route
          element={status === 'authenticated' ? <AppLayout /> : <Navigate to="/login" replace />}
        >
          <Route index element={<DashboardPage />} />
          <Route path="transactions" element={<TransactionsPage />} />
          <Route path="budgets" element={<BudgetsPage />} />
          <Route path="fraud" element={<FraudPage />} />
          <Route path="loans" element={<LoansPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="family" element={<FamilyPage />} />
          <Route path="assistant" element={<AssistantPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  )
}
