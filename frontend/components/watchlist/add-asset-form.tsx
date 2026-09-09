"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api, ApiError } from "@/lib/api";
import { ErrorBlock, LoadingBlock } from "@/components/ui/query-boundary";
import type { WatchlistOut } from "@/types/api";

export function AddAssetForm({
  watchedAssetIds,
  onAdded,
}: {
  watchedAssetIds: Set<string>;
  onAdded: (entry: WatchlistOut) => void;
}) {
  const assetsQuery = useApiQuery(() => api.listAssets());
  const [assetId, setAssetId] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const available = useMemo(() => {
    if (assetsQuery.status !== "success") return [];
    return assetsQuery.data.filter((a) => !watchedAssetIds.has(a.id));
  }, [assetsQuery, watchedAssetIds]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!assetId) {
      setError(new ApiError("validation", null, "اختر أصلًا لإضافته إلى المتابعة."));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const entry = await api.addWatchlistEntry({ asset_id: assetId, notes: notes.trim() || null });
      onAdded(entry);
      setAssetId("");
      setNotes("");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
    }
  }

  if (assetsQuery.status === "loading") return <LoadingBlock label="جارٍ تحميل الأصول..." />;
  if (assetsQuery.status === "error") return <ErrorBlock error={assetsQuery.error} onRetry={assetsQuery.refetch} />;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2.5">
      <div className="flex flex-col gap-2 sm:flex-row">
        <select
          value={assetId}
          onChange={(e) => setAssetId(e.target.value)}
          className="flex-1 rounded-xl border border-border bg-background px-3 py-2.5 text-sm text-foreground outline-none focus:border-primary"
        >
          <option value="">اختر أصلًا...</option>
          {available.map((asset) => (
            <option key={asset.id} value={asset.id}>
              {asset.symbol} — {asset.name}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={submitting || available.length === 0}
          className="shrink-0 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
        >
          {submitting ? "..." : "إضافة"}
        </button>
      </div>
      <input
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="ملاحظة (اختياري)"
        className="rounded-xl border border-border bg-background px-3 py-2 text-xs text-foreground outline-none focus:border-primary"
      />
      {available.length === 0 && assetsQuery.status === "success" ? (
        <p className="text-xs text-muted-foreground">جميع الأصول النشطة قيد المتابعة بالفعل.</p>
      ) : null}
      {error ? <ErrorBlock error={error} /> : null}
    </form>
  );
}
