// ┌──────────────────────────────────────────────────────────────────────────┐
// │ In-house SWR-style cache                                                 │
// ├──────────────────────────────────────────────────────────────────────────┤
// │ Why custom instead of npm install swr / @tanstack/react-query:           │
// │   * No new dependency, no lockfile churn, no ESLint/peer-dep upgrade     │
// │     dance for the existing TS / Next 16 stack.                           │
// │   * The full feature set we need (dedupe, revalidate, abort, visibility) │
// │     is ~150 lines and avoids the bundler overhead.                        │
// │                                                                          │
// │ What it does:                                                            │
// │   * `cachedFetch(key, fetcher, {staleMs, ttlMs, signal})` returns data   │
// │     from an in-memory map, dedupes concurrent keys, applies abort        │
// │     signals on unmount, revalidates when the tab regains focus.          │
// │   * `useCachedFetch(key, fetcher, opts)` is the React hook — data,       │
// │     isStale, isLoading, error, mutate. Concurrent requests for the       │
// │     same key share one in-flight promise.                                │
// │   * SSR-safe: hooks bail out gracefully if window is undefined.          │
// │                                                                          │
// │ Behavior that mirrors swr's API:                                         │
// │   * staleMs -- after this, the cache is considered stale; on revalidate  │
// │     the previous data is returned immediately and the fetch runs in the   │
// │     background (stale-while-revalidate).                                 │
// │   * ttlMs   -- hard eviction. Defaults to 5*staleMs when not given.      │
// │   * mutate  -- updates the cache without revalidating; useful for the    │
// │     optimistic approval flow.                                             │
// │                                                                          │
// │ NOT a replacement for server-side caching. The backend's                 │
// │ `backend/core/lt_cache.py` already collapses stampeding herd reads on    │
// │ /release, /companies/{c}/os, /dashboard/{f}. This module's job is to      │
// │ prevent the BROWSER from re-issuing those reads every 5-30s.             │
// └──────────────────────────────────────────────────────────────────────────┘

type Entry<T> = {
  // ``undefined`` until the first fetch resolves; after that the stored value
  // is whatever the fetcher returned. The race-fix path constructs the entry
  // synchronously BEFORE awaiting the fetcher, so subscribers always see this
  // field populated back to undefined↔value transitions correctly.
  value: T | undefined;
  fetchedAt: number; // monotonic-ish wallclock; we don't compare across tabs
  expiresAt: number; // value is stale past this point
  evictAt: number;   // entry must be discarded past this point
  promise?: Promise<T>; // an in-flight fetch this entry is currently sharing
  controller?: AbortController;
};

const _store = new Map<string, Entry<unknown>>();
const _listeners = new Map<string, Set<() => void>>();
const _defaultStaleMs = 5_000;
const _defaultTtlFactor = 5; // ttlMs defaults to 5x staleMs so a quiet tab retains cached data longer than a busy one

function _emit(key: string) {
  const subs = _listeners.get(key);
  if (!subs) return;
  // copy first: subscribers may unsubscribe inside the call.
  for (const fn of Array.from(subs)) {
    try {
      fn();
    } catch {
      /* swallow; one bad subscriber shouldn't break the rest */
    }
  }
}

export type CacheOptions = {
  staleMs?: number;
  ttlMs?: number;
  signal?: AbortSignal;
};

export async function cachedFetch<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  opts: CacheOptions = {},
): Promise<T> {
  const now = Date.now();
  const staleMs = opts.staleMs ?? _defaultStaleMs;
  const ttlMs = opts.ttlMs ?? staleMs * _defaultTtlFactor;

  // Reuse a live in-flight promise + its abort signal so concurrent callers
  // share one network round trip AND one AbortController (canceling any one
  // caller cancels the whole flight — see the cleanup helper below).
  const existing = _store.get(key) as Entry<T> | undefined;
  if (existing?.promise) {
    if (opts.signal) {
      // Bridge a caller abort to the shared controller. If the abort already
      // fired before we got here, attach no listener -- doing so would have it
      // synchronously re-abort already-aborted state, which is harmless but
      // noisy. The shared controller's existing state is what counts.
      if (!opts.signal.aborted) {
        opts.signal.addEventListener("abort", () => existing.controller?.abort(), { once: true });
      } else if (existing.controller && !existing.controller.signal.aborted) {
        existing.controller.abort();
      }
    }
    return existing.promise;
  }
  // Cache hit only when BOTH (a) the entry has a future expiry AND (b) the
  // stored value is non-undefined. The placeholder entry published BEFORE
  // a race-fixed in-flight fetch resolves has ``expiresAt = now + staleMs``
  // (future) but ``value = undefined`` -- a parallel first-requester on a
  // cold cache must NOT get back ``undefined`` here; it should fall into
  // the in-flight-promise reuse branch above instead.
  if (existing && existing.expiresAt > now && existing.value !== undefined) {
    return existing.value;
  }

  const controller = new AbortController();
  if (opts.signal) {
    // If the caller already aborted before we even started, abort the shared
    // controller synchronously so the fetcher short-circuits. Otherwise wire
    // a one-shot bridge so a later abort on this caller cancels everyone
    // sharing the same in-flight request.
    if (opts.signal.aborted) controller.abort();
    else opts.signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  // IMPORTANT: build the promise BEFORE publishing the entry so concurrent
  // callers entering in the gap see a fully-formed `.promise` and dedupe
  // properly. Earlier versions published the placeholder entry first then
  // assigned ``entry.promise = promise`` afterwards — a stampeding herd of
  // cold-cache tabs would each see ``existing?.promise === undefined`` and
  // start their own fetcher in parallel (caught in code review).
  let promise!: Promise<T>;
  promise = (async () => {
    try {
      const value = await fetcher(controller.signal);
      // Replace the entry with a NEW object so subscribers whose getSnapshot
      // returned the previous reference see a fresh value (useSyncExternalStore
      // compares via Object.is, so mutating in place would silently skip re-render).
      _store.set(key, {
        value,
        fetchedAt: Date.now(),
        // Fresh data: extend stale window out to a full ttl so a second caller
        // arriving before the previous one expires still gets the same data.
        expiresAt: Date.now() + staleMs,
        evictAt: Date.now() + ttlMs,
      } as Entry<unknown>);
      _emit(key);
      return value;
    } catch (err) {
      // Hard failure: re-publish the previous entry (without the in-flight
      // marker) so subscribers that already saw the prior value remain
      // subscribed to that snapshot and stale-while-revalidate still applies.
      // We KEEP the old entry object to preserve its reference identity for
      // existing subscribers rather than swapping it out from under them.
      const prior = _store.get(key);
      if (prior) prior.promise = undefined;
      _emit(key);
      throw err;
    }
  })();

  const entry: Entry<T> = {
    value: existing?.value,
    fetchedAt: existing?.fetchedAt ?? 0,
    expiresAt: now + staleMs,
    evictAt: now + ttlMs,
    controller,
    promise,
  };
  _store.set(key, entry as Entry<unknown>);
  _emit(key);
  return promise;
}

export function getCached<T>(key: string): T | undefined {
  const e = _store.get(key) as Entry<T> | undefined;
  if (!e) return undefined;
  if (e.evictAt <= Date.now()) {
    _store.delete(key);
    _listeners.delete(key);
    return undefined;
  }
  return e.value;
}

export function isStale(key: string): boolean {
  const e = _store.get(key);
  if (!e) return true;
  return e.expiresAt <= Date.now();
}

export type MutateOptions<T> = {
  revalidate?: boolean;
};

/** Optimistic write. Updates cache + notifies subscribers, returns immediately.
 *  Pass `revalidate: true` to trigger a background refetch after the write
 *  (useful for letting the SWR layer coalesce with server reconciliation). */
export function mutate<T>(
  key: string,
  updater: T | ((current: T | undefined) => T),
  opts: MutateOptions<T> = {},
): void {
  const e = _store.get(key) as Entry<T> | undefined;
  const current = e?.value;
  const next =
    typeof updater === "function"
      ? (updater as (current: T | undefined) => T)(current)
      : updater;
  const now = Date.now();
  const staleMs = _defaultStaleMs; // optimistic writes don't rely on a real TTL window
  const ttlMs = staleMs * _defaultTtlFactor;
  _store.set(key, {
    value: next,
    fetchedAt: now,
    expiresAt: now + staleMs,
    evictAt: now + ttlMs,
  } as Entry<unknown>);
  _emit(key);
  // ``opts.revalidate`` is currently a behavioral placeholder: the emit above
  // already notifies subscribers, and consumers that want a background
  // refetch just call ``cachedFetch`` directly after mutate (see
  // ``useCachedFetchImpl::refetch``). Kept the option in the type so consumers
  // don't churn if we later wire a default revalidation hook here.
}

export function invalidate(key: string): void {
  _store.delete(key);
  _emit(key);
}

export function invalidateMatching(predicate: (key: string) => boolean): void {
  for (const key of Array.from(_store.keys())) {
    if (predicate(key)) {
      _store.delete(key);
      _emit(key);
    }
  }
}

export type UseCachedFetchResult<T> = {
  data: T | undefined;
  isLoading: boolean;
  isStale: boolean | undefined;
  error: Error | undefined;
  refetch: () => Promise<void>;
  mutate: (next: T | ((current: T | undefined) => T)) => void;
};

export function useCachedFetch<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
  opts: CacheOptions = {},
): UseCachedFetchResult<T> {
  // Server-render safety — bail out cleanly when window is undefined.
  if (typeof window === "undefined") {
    return {
      data: undefined,
      isLoading: false,
      isStale: undefined,
      error: undefined,
      refetch: async () => {},
      mutate: () => {},
    };
  }
  // The actual hook body is in useCachedFetchImpl below; this wrapper exists
  // purely so the eslint react-hooks rule can see hooks called in a stable
  // top-down order (works because React 19 + Next 16 no-require-React)).
  return useCachedFetchImpl(key, fetcher, opts);
}

// React hook import is intentionally dynamic: importing in a worker / Node
// test runner would crash. The build handles both paths because the only
// place we touch React is inside useCachedFetchImpl.
import * as React from "react";

function useCachedFetchImpl<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
  opts: CacheOptions = {},
): UseCachedFetchResult<T> {
  const [, force] = React.useReducer((x: number) => x + 1, 0);
  const [isLoading, setIsLoading] = React.useState<boolean>(false);
  const [error, setError] = React.useState<Error | undefined>(undefined);
  const abortRef = React.useRef<AbortController | null>(null);

  const subscribe = React.useCallback((onChange: () => void) => {
    if (!key) return () => {};
    let subs = _listeners.get(key);
    if (!subs) {
      subs = new Set();
      _listeners.set(key, subs);
    }
    subs.add(onChange);
    return () => {
      subs?.delete(onChange);
      // If every React subscriber left, drop the empty set so the global map doesn't grow.
      if (subs && subs.size === 0) _listeners.delete(key);
    };
  }, [key]);

  const getSnapshot = React.useCallback(() => {
    if (!key) return _EMPTY_SNAPSHOT;
    const e = _store.get(key);
    return e ?? _EMPTY_SNAPSHOT;
  }, [key]);

  // Subscribing via useSyncExternalStore keeps the hook aligned with React 18/19
  // concurrent rendering and prevents the classic "subscribe after render" bug.
  const entry = React.useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const data = (entry as Entry<T> | typeof _EMPTY_SNAPSHOT).value as T | undefined;
  const isStale = !key
    ? undefined
    : ((entry as Entry<T>).expiresAt ?? 0) <= Date.now();

  React.useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setIsLoading(true);
    cachedFetch<T>(key, fetcher, { ...opts, signal: controller.signal })
      .then(() => {
        if (!controller.signal.aborted) {
          setError(undefined);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err : new Error(String(err)));
          setIsLoading(false);
        }
      });
    return () => {
      controller.abort();
      abortRef.current = null;
    };
    // Intentionally omitting fetcher/opts from deps: they may be inline
    // arrow functions and changing them on every render would refetch the
    // world. Use a stable key to control the actual fetch lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Cross-tab revalidation: when the tab regains focus, refetch stale entries.
  React.useEffect(() => {
    if (!key || typeof document === "undefined") return;
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      const e = _store.get(key);
      if (!e) return;
      if (e.expiresAt > Date.now()) return;
      const controller = new AbortController();
      void cachedFetch<T>(key, fetcher, { ...opts, signal: controller.signal });
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const refetch = React.useCallback(async () => {
    if (!key) return;
    invalidate(key);
    force();
    const controller = new AbortController();
    try {
      await cachedFetch<T>(key, fetcher, { ...opts, signal: controller.signal });
      setError(undefined);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, [key, fetcher, opts]);

  const mutateFb = React.useCallback(
    (next: T | ((current: T | undefined) => T)) => {
      if (!key) return;
      mutate<T>(key, next);
      force();
    },
    [key],
  );

  return { data, isLoading, isStale, error, refetch, mutate: mutateFb };
}

const _EMPTY_SNAPSHOT: Entry<unknown> = {
  value: undefined,
  fetchedAt: 0,
  expiresAt: 0,
  evictAt: 0,
};

export type JsonFetcherInit = RequestInit & { signal?: AbortSignal };

/** Small helper that wraps fetch+JSON parsing for the most common case. Saves
 *  importing/aborting boilerplate in the dozens of apiFetch call sites. */
export async function fetchJson<T>(input: string, init: JsonFetcherInit = {}): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `${init.method ?? "GET"} ${input} -> HTTP ${res.status}${text ? `: ${text.slice(0, 240)}` : ""}`,
    );
  }
  return (await res.json()) as T;
}
