/**
 * Small async-data hook.
 *
 * The API has no client cache, so every screen refetches on mount. `useAsync`
 * exists so that pattern is written once and, more importantly, so a late
 * response from a screen the user already left cannot overwrite fresher state.
 * The `cancelled` flag in the cleanup is what prevents that.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '@/lib/api'

export interface AsyncState<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
}

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    loader()
      .then((result) => {
        if (cancelled || !mounted.current) return
        setData(result)
      })
      .catch((cause: unknown) => {
        if (cancelled || !mounted.current) return
        setError(cause instanceof ApiError ? cause.detail : 'Something went wrong.')
      })
      .finally(() => {
        if (cancelled || !mounted.current) return
        setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  return { data, error, loading, reload }
}

/** Trigger a reload, for "save succeeded, refetch the list" flows. */
export function useRefresh(): () => void {
  const [, setNonce] = useState(0)
  return useCallback(() => setNonce((n) => n + 1), [])
}

/**
 * Submit-with-state for forms.
 *
 * `submitting` exists to stop double submission: without it, a fast double-click
 * on Save creates two transactions.
 */
export function useSubmit<TArgs, TResult>(
  action: (args: TArgs) => Promise<TResult>,
): {
  submitting: boolean
  error: string | null
  fieldErrors: Record<string, string>
  submit: (args: TArgs) => Promise<TResult | null>
  clearError: () => void
} {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const submit = useCallback(
    async (args: TArgs) => {
      if (submitting) return null
      setSubmitting(true)
      setError(null)
      setFieldErrors({})
      try {
        return await action(args)
      } catch (cause: unknown) {
        if (cause instanceof ApiError) {
          setError(cause.detail)
          setFieldErrors(
            Object.fromEntries(cause.fields.map((f) => [f.field, f.message])),
          )
        } else {
          setError(cause instanceof Error ? cause.message : 'Something went wrong.')
        }
        return null
      } finally {
        setSubmitting(false)
      }
    },
    [action, submitting],
  )

  const clearError = useCallback(() => {
    setError(null)
    setFieldErrors({})
  }, [])

  return { submitting, error, fieldErrors, submit, clearError }
}
