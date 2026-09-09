"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";

export type QueryState<T> =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "success"; data: T };

/**
 * Minimal server-state hook: fetches on mount (and whenever `deps`
 * change), exposes a `refetch` for retry buttons and post-mutation
 * refreshes. No caching layer / large state library — see
 * ARCHITECTURE.md, "prefer simple React/Next.js patterns if sufficient."
 */
export function useApiQuery<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<QueryState<T>>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  // Keep the latest fetcher available to the effect below without
  // forcing callers to memoize their (often inline) fetcher function.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const refetch = useCallback(() => setReloadToken((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- standard fetch-on-effect data loading; the `cancelled` flag below already guards against a stale response overwriting newer state.
    setState({ status: "loading" });
    fetcherRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ status: "success", data });
      })
      .catch((err) => {
        if (cancelled) return;
        const apiError =
          err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع.");
        setState({ status: "error", error: apiError });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken]);

  return { ...state, refetch };
}
