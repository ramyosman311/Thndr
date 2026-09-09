"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { StatusPill } from "@/components/ui/status-pill";
import { ErrorBlock, LoadingBlock } from "@/components/ui/query-boundary";
import { formatCurrency, formatPercent } from "@/lib/format";
import { inflowStatusMeta, strategyStatusMeta } from "@/lib/status-labels";
import type { InflowAllocationOut, InflowRecommendationOut } from "@/types/api";

const AMOUNT_PATTERN = /^\d+(\.\d{1,2})?$/;

export default function InflowPage() {
  const [amount, setAmount] = useState("");
  const [validationMessage, setValidationMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<InflowAllocationOut | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setValidationMessage(null);
    setError(null);

    const trimmed = amount.trim();
    if (!AMOUNT_PATTERN.test(trimmed) || Number(trimmed) <= 0) {
      setValidationMessage("أدخل مبلغًا صحيحًا أكبر من صفر (حتى خانتين عشريتين).");
      return;
    }

    setSubmitting(true);
    setResult(null);
    try {
      const data = await api.allocateCashFlow(trimmed);
      setResult(data);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("network", null, "حدث خطأ غير متوقع."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold text-foreground">التوزيع الذكي للسيولة الجديدة</h1>

      <Card>
        <CardHeader
          title="لديك مبلغ جديد؟"
          subtitle="أدخل المبلغ لعرض توصية بتوزيعه على فئات المحفظة — لن يتم تنفيذ أي عملية شراء أو بيع تلقائيًا."
        />
        <CardBody>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">المبلغ الجديد</span>
              <div className="flex items-center gap-2">
                <input
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="5000.00"
                  aria-describedby={validationMessage ? "amount-error" : undefined}
                  aria-invalid={validationMessage ? true : undefined}
                  className="tabular-nums w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm text-foreground outline-none focus:border-primary"
                />
                <button
                  type="submit"
                  disabled={submitting}
                  className="shrink-0 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
                >
                  {submitting ? "..." : "احسب التوصية"}
                </button>
              </div>
              {validationMessage ? (
                <span id="amount-error" role="alert" className="text-xs text-danger">
                  {validationMessage}
                </span>
              ) : null}
            </label>
          </form>
        </CardBody>
      </Card>

      {submitting ? <LoadingBlock label="جارٍ حساب التوصية..." /> : null}
      {error ? <ErrorBlock error={error} onRetry={() => setError(null)} /> : null}
      {result ? <InflowResult result={result} /> : null}
    </div>
  );
}

function InflowResult({ result }: { result: InflowAllocationOut }) {
  const strategyMeta = strategyStatusMeta(result.strategy_status);
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-2xl border border-primary/30 bg-accent p-3 text-center text-xs font-semibold text-accent-foreground">
        هذه توصية فقط — لم يتم تسجيل أي معاملة أو تعديل أي حيازة فعلية.
      </div>

      <Card>
        <CardHeader title="ملخص التوصية" action={<StatusPill label={strategyMeta.label} tone={strategyMeta.tone} />} />
        <CardBody>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <p className="text-muted-foreground">المبلغ المطلوب</p>
              <p className="tabular-nums mt-1 font-bold text-foreground">{formatCurrency(result.requested_cash)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">تم توزيعه</p>
              <p className="tabular-nums mt-1 font-bold text-success">{formatCurrency(result.allocated_cash)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">غير مُوزَّع</p>
              <p className="tabular-nums mt-1 font-bold text-muted-foreground">
                {formatCurrency(result.unallocated_cash)}
              </p>
            </div>
          </div>
          {!result.strategy_is_valid ? (
            <p className="mt-3 rounded-lg bg-warning-muted px-2.5 py-1.5 text-[11px] text-warning">
              ملاحظة: الاستراتيجية غير مكتملة حاليًا، وهذا لا يمنع توزيع السيولة على الفئات المُهيّأة بالفعل.
            </p>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="التوصية لكل فئة" />
        <CardBody className="flex flex-col divide-y divide-border">
          {result.recommendations.map((rec) => (
            <RecommendationRow key={rec.strategy_bucket_id} rec={rec} />
          ))}
        </CardBody>
      </Card>
    </div>
  );
}

function RecommendationRow({ rec }: { rec: InflowRecommendationOut }) {
  const meta = inflowStatusMeta(rec.status);
  return (
    <div className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">{rec.bucket_name}</span>
        <StatusPill label={meta.label} tone={meta.tone} />
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          القيمة الحالية: <span className="tabular-nums text-foreground">{formatCurrency(rec.current_value)}</span>
          {rec.current_percent !== null ? (
            <span className="tabular-nums"> ({formatPercent(rec.current_percent)})</span>
          ) : null}
        </span>
        <span className="tabular-nums font-bold text-primary">
          {rec.eligible ? `+${formatCurrency(rec.allocated_amount)}` : formatCurrency(rec.allocated_amount)}
        </span>
      </div>
    </div>
  );
}
