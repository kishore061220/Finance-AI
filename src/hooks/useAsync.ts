/**
 * Fetch-on-mount hook.
 *
 * Wraps the three states every data screen needs - loading, error, data - plus a
 * `reload`, and guards against setting state after unmount. That last part
 * matters more than it looks: without it, a slow response on a screen the user
 * has already navigated away from produces a React warning, and on a fast
 * double-tap it produces a race where the older response overwrites the newer one.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../services/api';

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  /** True until the first request settles, so a refresh does not blank the screen. */
  initial: boolean;
  reload: () => void;
}

export function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [initial, setInitial] = useState(true);

  // Monotonic request id. A response whose id is not the latest is discarded,
  // so a slow first request cannot overwrite the result of a later one.
  const requestId = useRef(0);
  const mounted = useRef(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    const id = (requestId.current += 1);
    setLoading(true);
    try {
      const result = await fetcherRef.current();
      if (!mounted.current || id !== requestId.current) return;
      setData(result);
      setError(null);
    } catch (cause) {
      if (!mounted.current || id !== requestId.current) return;
      setError(cause instanceof ApiError ? cause : new ApiError('Something went wrong.', 0));
    } finally {
      if (mounted.current && id === requestId.current) {
        setLoading(false);
        setInitial(false);
      }
    }
  }, []);

  useEffect(() => {
    void run();
    // `run` is stable; the caller controls re-fetching through `deps`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, run]);

  const reload = useCallback(() => {
    void run();
  }, [run]);

  return { data, error, loading, initial, reload };
}

/**
 * Debounce a value.
 *
 * Used for search-as-you-type, where firing a request per keystroke would send
 * one query per character and race the responses.
 */
export function useDebounced<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
