import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas px-4 text-center">
      <p className="text-sm font-semibold uppercase tracking-wide text-accent">404</p>
      <h1 className="mt-2 text-2xl">Page not found</h1>
      <p className="mt-2 text-sm text-muted">
        That page does not exist. It may have moved, or the link may be out of date.
      </p>
      <Link to="/" className="mt-6 text-sm font-medium text-accent hover:underline">
        Back to the dashboard
      </Link>
    </div>
  )
}
