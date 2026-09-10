"use client";

import { useState, type FormEvent } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { QueryBoundary, EmptyBlock, ErrorBlock } from "@/components/ui/query-boundary";
import { StatusPill } from "@/components/ui/status-pill";
import { PlusIcon } from "@/components/icons";
import { strategyStatusMeta } from "@/lib/status-labels";
import { formatPercent } from "@/lib/format";
import type { AllocationTargetOut, StrategyBucketOut } from "@/types/api";

const inputClass =
  "w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary";
const labelClass = "text-xs font-medium text-muted-foreground";

export function StrategyAdmin() {
  const bucketsQuery = useApiQuery(() => api.listStrategyBuckets(true));
  const targetsQuery = useApiQuery(() => api.listAllocationTargets(true));
  const validationQuery = useApiQuery(() => api.strategyValidation());
  const [showCreateBucket, setShowCreateBucket] = useState(false);

  function refetchAll() {
    bucketsQuery.refetch();
    targetsQuery.refetch();
    validationQuery.refetch();
  }

  return (
    <div className="flex flex-col gap-3">
      {validationQuery.status === "success" ? (
        <ValidationBanner
          status={validationQuery.data.status}
          explanation={validationQuery.data.explanation}
          totalTargetPercent={validationQuery.data.total_target_percent}
          expectedTargetPercent={validationQuery.data.expected_target_percent}
        />
      ) : null}

      <Card>
        <CardHeader
          title="الفئات الاستراتيجية"
          action={
            <button
              type="button"
              onClick={() => setShowCreateBucket((v) => !v)}
              className="inline-flex items-center gap-1 rounded-full bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
            >
              <PlusIcon width={14} height={14} />
              فئة جديدة
            </button>
          }
        />
        <CardBody className="flex flex-col gap-3">
          {showCreateBucket ? (
            <CreateBucketForm onCreated={() => { setShowCreateBucket(false); refetchAll(); }} onCancel={() => setShowCreateBucket(false)} />
          ) : null}
          <QueryBoundary state={bucketsQuery} onRetry={bucketsQuery.refetch} loadingLabel="جارٍ تحميل الفئات...">
            {(buckets) =>
              buckets.length === 0 ? (
                <EmptyBlock title="لا توجد فئات استراتيجية بعد" />
              ) : (
                <ul className="flex flex-col divide-y divide-border">
                  {buckets.map((bucket) => (
                    <BucketRow key={bucket.id} bucket={bucket} onChanged={refetchAll} />
                  ))}
                </ul>
              )
            }
          </QueryBoundary>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="نسب التوزيع المستهدف" subtitle="هدف، حد أقصى، وأولوية لكل فئة" />
        <CardBody className="flex flex-col gap-3">
          <QueryBoundary state={bucketsQuery} loadingLabel="...">
            {(buckets) => (
              <QueryBoundary state={targetsQuery} onRetry={targetsQuery.refetch} loadingLabel="جارٍ تحميل الأهداف...">
                {(targets) => (
                  <TargetsSection
                    buckets={buckets}
                    targets={targets}
                    onChanged={refetchAll}
                  />
                )}
              </QueryBoundary>
            )}
          </QueryBoundary>
        </CardBody>
      </Card>
    </div>
  );
}

function ValidationBanner({
  status,
  explanation,
  totalTargetPercent,
  expectedTargetPercent,
}: {
  status: string;
  explanation: string;
  totalTargetPercent: string;
  expectedTargetPercent: string;
}) {
  const meta = strategyStatusMeta(status);
  return (
    <Card>
      <CardBody className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <StatusPill label={meta.label} tone={meta.tone} />
          <span className="tabular-nums text-xs text-muted-foreground">
            {formatPercent(totalTargetPercent)} من {formatPercent(expectedTargetPercent)}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">{explanation}</p>
      </CardBody>
    </Card>
  );
}

function CreateBucketForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createStrategyBucket({ name, description: description.trim() || null });
      setName("");
      setDescription("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3">
      <label className="flex flex-col gap-1">
        <span className={labelClass}>اسم الفئة</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required className={inputClass} />
      </label>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>وصف (اختياري)</span>
        <input value={description} onChange={(e) => setDescription(e.target.value)} className={inputClass} />
      </label>
      {error ? <ErrorBlock error={error} /> : null}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
        >
          {submitting ? "..." : "إنشاء"}
        </button>
        <button type="button" onClick={onCancel} className="text-xs font-medium text-muted-foreground hover:text-foreground">
          إلغاء
        </button>
      </div>
    </form>
  );
}

function BucketRow({ bucket, onChanged }: { bucket: StrategyBucketOut; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(bucket.name);
  const [description, setDescription] = useState(bucket.description ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateStrategyBucket(bucket.id, { name, description: description.trim() || null });
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleActive() {
    setBusy(true);
    setError(null);
    try {
      if (bucket.is_active) await api.deactivateStrategyBucket(bucket.id);
      else await api.activateStrategyBucket(bucket.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-foreground">{bucket.name}</span>
            <StatusPill label={bucket.is_active ? "نشطة" : "معطّلة"} tone={bucket.is_active ? "success" : "neutral"} />
          </div>
          {bucket.description ? <p className="truncate text-xs text-muted-foreground">{bucket.description}</p> : null}
        </div>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium text-primary hover:bg-accent"
        >
          {editing ? "إغلاق" : "تعديل"}
        </button>
      </div>
      {editing ? (
        <form onSubmit={handleSave} className="flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>الاسم</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>الوصف</span>
            <input value={description} onChange={(e) => setDescription(e.target.value)} className={inputClass} />
          </label>
          {error ? <ErrorBlock error={error} /> : null}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
            >
              {busy ? "..." : "حفظ"}
            </button>
            <button
              type="button"
              onClick={handleToggleActive}
              disabled={busy}
              className="rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-foreground disabled:opacity-50"
            >
              {bucket.is_active ? "تعطيل" : "تفعيل"}
            </button>
          </div>
        </form>
      ) : null}
    </li>
  );
}

function TargetsSection({
  buckets,
  targets,
  onChanged,
}: {
  buckets: StrategyBucketOut[];
  targets: AllocationTargetOut[];
  onChanged: () => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const bucketNameById = Object.fromEntries(buckets.map((b) => [b.id, b.name]));
  const bucketsWithoutTarget = buckets.filter((b) => !targets.some((t) => t.strategy_bucket_id === b.id));

  return (
    <div className="flex flex-col gap-3">
      {bucketsWithoutTarget.length > 0 ? (
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          className="inline-flex w-fit items-center gap-1 rounded-full bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
        >
          <PlusIcon width={14} height={14} />
          هدف جديد
        </button>
      ) : null}
      {showCreate ? (
        <CreateTargetForm
          buckets={bucketsWithoutTarget}
          onCreated={() => {
            setShowCreate(false);
            onChanged();
          }}
          onCancel={() => setShowCreate(false)}
        />
      ) : null}
      {targets.length === 0 ? (
        <EmptyBlock title="لا توجد أهداف توزيع بعد" />
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {targets.map((target) => (
            <TargetRow
              key={target.id}
              target={target}
              bucketName={bucketNameById[target.strategy_bucket_id] ?? "—"}
              onChanged={onChanged}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function CreateTargetForm({
  buckets,
  onCreated,
  onCancel,
}: {
  buckets: StrategyBucketOut[];
  onCreated: () => void;
  onCancel: () => void;
}) {
  const [bucketId, setBucketId] = useState(buckets[0]?.id ?? "");
  const [targetPercent, setTargetPercent] = useState("");
  const [maximumPercent, setMaximumPercent] = useState("");
  const [priority, setPriority] = useState("0");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createAllocationTarget({
        strategy_bucket_id: bucketId,
        target_percent: targetPercent.trim() || null,
        maximum_percent: maximumPercent.trim() || null,
        priority: Number(priority) || 0,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="col-span-2 flex flex-col gap-1">
          <span className={labelClass}>الفئة</span>
          <select value={bucketId} onChange={(e) => setBucketId(e.target.value)} className={inputClass}>
            {buckets.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>الهدف %</span>
          <input value={targetPercent} onChange={(e) => setTargetPercent(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>الحد الأقصى %</span>
          <input value={maximumPercent} onChange={(e) => setMaximumPercent(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>الأولوية</span>
          <input value={priority} onChange={(e) => setPriority(e.target.value)} className={inputClass} />
        </label>
      </div>
      {error ? <ErrorBlock error={error} /> : null}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
        >
          {submitting ? "..." : "إنشاء"}
        </button>
        <button type="button" onClick={onCancel} className="text-xs font-medium text-muted-foreground hover:text-foreground">
          إلغاء
        </button>
      </div>
    </form>
  );
}

function TargetRow({
  target,
  bucketName,
  onChanged,
}: {
  target: AllocationTargetOut;
  bucketName: string;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [targetPercent, setTargetPercent] = useState(target.target_percent ?? "");
  const [maximumPercent, setMaximumPercent] = useState(target.maximum_percent ?? "");
  const [priority, setPriority] = useState(String(target.priority));
  const [allowNewBuy, setAllowNewBuy] = useState(target.allow_new_buy);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateAllocationTarget(target.id, {
        ...(targetPercent.trim() ? { target_percent: targetPercent.trim() } : { clear_target_percent: true }),
        ...(maximumPercent.trim() ? { maximum_percent: maximumPercent.trim() } : { clear_maximum_percent: true }),
        priority: Number(priority) || 0,
        allow_new_buy: allowNewBuy,
      });
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="text-sm font-bold text-foreground">{bucketName}</span>
          <p className="text-[11px] text-muted-foreground">
            هدف: {target.target_percent ? formatPercent(target.target_percent) : "—"} · حد أقصى:{" "}
            {target.maximum_percent ? formatPercent(target.maximum_percent) : "—"} · أولوية: {target.priority}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium text-primary hover:bg-accent"
        >
          {editing ? "إغلاق" : "تعديل"}
        </button>
      </div>
      {editing ? (
        <form onSubmit={handleSave} className="flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3">
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1">
              <span className={labelClass}>الهدف %</span>
              <input value={targetPercent} onChange={(e) => setTargetPercent(e.target.value)} className={inputClass} />
            </label>
            <label className="flex flex-col gap-1">
              <span className={labelClass}>الحد الأقصى %</span>
              <input value={maximumPercent} onChange={(e) => setMaximumPercent(e.target.value)} className={inputClass} />
            </label>
            <label className="flex flex-col gap-1">
              <span className={labelClass}>الأولوية</span>
              <input value={priority} onChange={(e) => setPriority(e.target.value)} className={inputClass} />
            </label>
            <label className="flex items-center gap-2 self-end pb-2 text-xs text-foreground">
              <input
                type="checkbox"
                checked={allowNewBuy}
                onChange={(e) => setAllowNewBuy(e.target.checked)}
                className="h-4 w-4 rounded border-border"
              />
              السماح بالشراء الجديد
            </label>
          </div>
          {error ? <ErrorBlock error={error} /> : null}
          <button
            type="submit"
            disabled={busy}
            className="w-fit rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
          >
            {busy ? "..." : "حفظ"}
          </button>
        </form>
      ) : null}
    </li>
  );
}
