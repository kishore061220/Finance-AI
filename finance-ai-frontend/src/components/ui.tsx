/**
 * Shared primitives.
 *
 * Kept deliberately small: each one is a thin wrapper over a `<div>` or
 * `<button>` with class names, so screen code stays about screens. The variants
 * are typed unions rather than free strings, which means a typo like
 * `variant="primray"` is a compile error instead of an unstyled button.
 */

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'

import { ApiError } from '@/lib/api'

// ---------------------------------------------------------------- layout

export function Card({
  title,
  action,
  children,
  className = '',
}: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card p-5 ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-start justify-between gap-3">
          {title && <h2 className="text-base">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {action}
    </header>
  )
}

// ---------------------------------------------------------------- buttons

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
type Size = 'sm' | 'md'

const variantClasses: Record<Variant, string> = {
  primary: 'bg-accent hover:bg-accent-strong text-white',
  secondary: 'bg-surface-2 hover:bg-border-subtle text-text-strong border border-border-subtle',
  danger: 'bg-danger hover:opacity-90 text-white',
  ghost: 'bg-transparent hover:bg-surface-2 text-text',
}

const sizeClasses: Record<Size, string> = {
  sm: 'px-2.5 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className = '',
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
  loading?: boolean
}) {
  return (
    <button
      {...rest}
      // A loading button must be disabled too, or a second click submits again.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55 ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
    >
      {loading && (
        <span
          aria-hidden="true"
          className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  )
}

// ---------------------------------------------------------------- form fields

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string
  htmlFor: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div>
      <label className="field-label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint && !error && (
        <p className="mt-1 text-xs text-muted">{hint}</p>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export function TextInput({
  id,
  error,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { error?: boolean }) {
  return (
    <input
      id={id}
      aria-invalid={error || undefined}
      className={`field-input ${error ? 'border-danger' : ''}`}
      {...rest}
    />
  )
}

export function Select({
  id,
  error,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & { error?: boolean }) {
  return (
    <select
      id={id}
      aria-invalid={error || undefined}
      className={`field-input ${error ? 'border-danger' : ''}`}
      {...rest}
    >
      {children}
    </select>
  )
}

// ---------------------------------------------------------------- status

export function Alert({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'error' | 'warning' | 'success'
  children: ReactNode
}) {
  const tones: Record<string, string> = {
    info: 'border-accent/40 bg-accent/10 text-text',
    error: 'border-danger/40 bg-danger/10 text-danger',
    warning: 'border-warning/40 bg-warning/10 text-warning',
    success: 'border-positive/40 bg-positive/10 text-positive',
  }
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`rounded-lg border px-3 py-2 text-sm ${tones[tone]}`}>
      {children}
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 py-8 text-sm text-muted">
      <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      {label}…
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="card flex flex-col items-center gap-2 px-6 py-12 text-center">
      <p className="font-medium text-text-strong">{title}</p>
      {description && <p className="max-w-sm text-sm text-muted">{description}</p>}
      {action}
    </div>
  )
}

/**
 * Render an error state.
 *
 * A 401 here means the session died between the page load and this request. It
 * is reported as such rather than as a generic failure, because the fix is
 * different: sign in again.
 */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const isApi = error instanceof ApiError
  const isAuth = isApi && error.isAuthError
  const isNetwork = isApi && error.isNetworkError

  const message = isApi
    ? error.detail
    : error instanceof Error
      ? error.message
      : 'Something went wrong.'

  const heading = isAuth
    ? 'Your session expired'
    : isNetwork
      ? 'Cannot reach the API'
      : 'Could not load this'

  return (
    <Alert tone="error">
      <p className="font-medium">{heading}</p>
      <p className="mt-1">{message}</p>
      {onRetry && !isAuth && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </Alert>
  )
}

/**
 * A value that is genuinely absent.
 *
 * Separate from `EmptyState`: this is for one field with no data, not a whole
 * panel being empty.
 */
export function MissingValue({ children = 'Not available' }: { children?: ReactNode }) {
  return <span className="text-muted">{children}</span>
}
