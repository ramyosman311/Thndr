import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { StatusPill } from "@/components/ui/status-pill";
import { formatPercent, formatCurrency } from "@/lib/format";
import { maximumStatusMeta, minimumStatusMeta, strategyStatusMeta, targetStatusMeta } from "@/lib/status-labels";
import type { AllocationRuleOut, BucketAllocationOut, StrategyValidationOut } from "@/types/api";

export function BucketCard({ bucket, currency }: { bucket: BucketAllocationOut; currency: string }) {
  return (
    <Card>
      <CardHeader
        title={bucket.bucket_name}
        subtitle={
          bucket.excluded_from_risk_allocation
            ? "مستبعد من نسبة التخصيص الاستثماري (نقد احتياطي)"
            : undefined
        }
      />
      <CardBody className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <Field label="القيمة الحالية" value={formatCurrency(bucket.actual_value, currency)} />
          <Field label="٪ من إجمالي المحفظة" value={formatPercent(bucket.total_portfolio_percent)} />
          <Field
            label="٪ من الأساس الاستثماري"
            value={bucket.risk_allocation_percent !== null ? formatPercent(bucket.risk_allocation_percent) : "غير محسوبة"}
          />
          <Field label="الهدف" value={bucket.target_percent !== null ? formatPercent(bucket.target_percent) : "بدون هدف"} />
          <Field
            label="الحد الأدنى"
            value={bucket.minimum_percent !== null ? formatPercent(bucket.minimum_percent) : "—"}
          />
          <Field
            label="الحد الأقصى"
            value={bucket.maximum_percent !== null ? formatPercent(bucket.maximum_percent) : "—"}
          />
          <Field
            label="الشراء الجديد"
            value={bucket.allow_new_buy === null ? "غير مُهيّأ" : bucket.allow_new_buy ? "مسموح" : "موقوف"}
          />
          <Field label="مسموح بالشراء الآن" value={bucket.buy_allowed ? "نعم" : "لا"} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {(() => {
            const t = targetStatusMeta(bucket.target_status);
            const m = minimumStatusMeta(bucket.minimum_status);
            const x = maximumStatusMeta(bucket.maximum_status);
            return (
              <>
                <StatusPill label={t.label} tone={t.tone} />
                <StatusPill label={m.label} tone={m.tone} />
                <StatusPill label={x.label} tone={x.tone} />
              </>
            );
          })()}
        </div>
      </CardBody>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-muted-foreground">{label}</p>
      <p className="tabular-nums font-semibold text-foreground">{value}</p>
    </div>
  );
}

export function StrategyDetailCard({ validation }: { validation: StrategyValidationOut }) {
  const meta = strategyStatusMeta(validation.status);
  return (
    <Card>
      <CardHeader title="تفاصيل الاستراتيجية" action={<StatusPill label={meta.label} tone={meta.tone} />} />
      <CardBody className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">{validation.explanation}</p>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <Field label="إجمالي نسب الاستهداف" value={formatPercent(validation.total_target_percent)} />
          <Field label="النسبة المتوقعة" value={formatPercent(validation.expected_target_percent)} />
        </div>

        {validation.field_errors.length > 0 ? (
          <RuleGroup
            title="أخطاء في الإعداد"
            rows={validation.field_errors.map((e) => ({
              strategy_bucket_id: e.strategy_bucket_id,
              bucket_name: e.bucket_name,
              detail: e.message,
            }))}
            tone="danger"
          />
        ) : null}

        {validation.target_rows.length > 0 ? (
          <AllocationRuleGroup title="فئات بنسبة استهداف" rows={validation.target_rows} />
        ) : null}

        {validation.maximum_only_rows.length > 0 ? (
          <AllocationRuleGroup
            title="فئات بحد أقصى فقط (قيد وليست وجهة تدفق)"
            rows={validation.maximum_only_rows}
          />
        ) : null}

        {validation.excluded_emergency_rows.length > 0 ? (
          <AllocationRuleGroup title="قاعدة الفئة الاحتياطية (مستبعدة)" rows={validation.excluded_emergency_rows} />
        ) : null}
      </CardBody>
    </Card>
  );
}

function AllocationRuleGroup({ title, rows }: { title: string; rows: AllocationRuleOut[] }) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-foreground">{title}</p>
      <ul className="flex flex-col gap-1.5">
        {rows.map((row) => (
          <li
            key={row.strategy_bucket_id}
            className="flex items-center justify-between rounded-lg bg-muted px-2.5 py-1.5 text-xs"
          >
            <span className="font-medium text-foreground">{row.bucket_name}</span>
            <span className="tabular-nums text-muted-foreground">
              هدف: {row.target_percent !== null ? formatPercent(row.target_percent) : "—"} · أقصى:{" "}
              {row.maximum_percent !== null ? formatPercent(row.maximum_percent) : "—"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RuleGroup({
  title,
  rows,
  tone,
}: {
  title: string;
  rows: { strategy_bucket_id: string; bucket_name: string; detail: string }[];
  tone: "danger";
}) {
  return (
    <div>
      <p className={`mb-2 text-xs font-semibold ${tone === "danger" ? "text-danger" : "text-foreground"}`}>{title}</p>
      <ul className="flex flex-col gap-1.5">
        {rows.map((row) => (
          <li key={row.strategy_bucket_id} className="rounded-lg bg-danger-muted px-2.5 py-1.5 text-xs text-danger">
            <span className="font-medium">{row.bucket_name}:</span> {row.detail}
          </li>
        ))}
      </ul>
    </div>
  );
}
