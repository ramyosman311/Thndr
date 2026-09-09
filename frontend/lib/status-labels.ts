/**
 * Arabic display labels + visual tone for every backend-defined status
 * string. This is presentation only: it translates and colors statuses
 * the backend already computed — it never invents a new status or
 * changes what a status means. See FINANCIAL_RULES.md and
 * domain/allocation_engine.py / inflow_allocator.py / alert_engine.py
 * for the authoritative meaning of each value.
 */
export type Tone = "success" | "warning" | "danger" | "neutral" | "info";

export interface StatusMeta {
  label: string;
  tone: Tone;
}

const fallback = (raw: string): StatusMeta => ({ label: raw, tone: "neutral" });

export const TARGET_STATUS: Record<string, StatusMeta> = {
  NO_TARGET: { label: "بدون هدف محدد", tone: "neutral" },
  UNDERWEIGHT: { label: "أقل من الهدف", tone: "info" },
  ON_TARGET: { label: "عند الهدف", tone: "success" },
  OVERWEIGHT: { label: "أعلى من الهدف", tone: "warning" },
};

export const MINIMUM_STATUS: Record<string, StatusMeta> = {
  NO_MINIMUM: { label: "بدون حد أدنى", tone: "neutral" },
  ABOVE_MINIMUM: { label: "أعلى من الحد الأدنى", tone: "success" },
  MINIMUM_BREACHED: { label: "أقل من الحد الأدنى", tone: "danger" },
};

export const MAXIMUM_STATUS: Record<string, StatusMeta> = {
  NO_MAXIMUM: { label: "بدون حد أقصى", tone: "neutral" },
  WITHIN_MAXIMUM: { label: "ضمن الحد الأقصى", tone: "success" },
  MAXIMUM_BREACHED: { label: "تجاوز الحد الأقصى", tone: "danger" },
};

export const STRATEGY_STATUS: Record<string, StatusMeta> = {
  VALID: { label: "الاستراتيجية مكتملة", tone: "success" },
  INCOMPLETE_TARGET_ALLOCATION: { label: "توزيع الاستهداف غير مكتمل", tone: "warning" },
  OVERALLOCATED_TARGET_ALLOCATION: { label: "توزيع الاستهداف يتجاوز 100%", tone: "danger" },
  EMPTY_CONFIGURATION: { label: "لا توجد إعدادات استراتيجية بعد", tone: "neutral" },
  INVALID_TARGET_VALUE: { label: "قيمة استهداف غير صالحة", tone: "danger" },
  INVALID_MIN_MAX_CONFIGURATION: { label: "إعداد حد أدنى/أقصى غير صالح", tone: "danger" },
};

export const INFLOW_STATUS: Record<string, StatusMeta> = {
  ELIGIBLE: { label: "تم التخصيص", tone: "success" },
  TARGET_GAP: { label: "فجوة عن الهدف (لم يُخصَّص لها هذه المرة)", tone: "info" },
  MAXIMUM_LIMIT: { label: "الحد الأقصى يمنع مزيدًا من التخصيص", tone: "warning" },
  BUY_DISABLED: { label: "الشراء الجديد موقوف لهذه الفئة", tone: "neutral" },
  EMERGENCY_EXCLUDED: { label: "مستبعد كنقد احتياطي", tone: "neutral" },
  NO_TARGET: { label: "بدون هدف — حد أقصى فقط", tone: "neutral" },
  AT_TARGET: { label: "عند الهدف بالفعل", tone: "success" },
  OVER_TARGET: { label: "أعلى من الهدف بالفعل", tone: "warning" },
  NO_CAPACITY: { label: "لا توجد قيمة استثمارية بعد", tone: "neutral" },
};

export const ALERT_TYPE_LABEL: Record<string, string> = {
  ALLOCATION_BREACH: "تجاوز نسبة التخصيص",
  PRICE_TARGET: "سعر مستهدف",
  DIP_BUY: "فرصة شراء عند انخفاض السعر",
  REBALANCE_SUGGESTED: "اقتراح إعادة توازن",
  INCOME_MATURITY: "استحقاق دخل دوري",
};

export function targetStatusMeta(status: string): StatusMeta {
  return TARGET_STATUS[status] ?? fallback(status);
}
export function minimumStatusMeta(status: string): StatusMeta {
  return MINIMUM_STATUS[status] ?? fallback(status);
}
export function maximumStatusMeta(status: string): StatusMeta {
  return MAXIMUM_STATUS[status] ?? fallback(status);
}
export function strategyStatusMeta(status: string): StatusMeta {
  return STRATEGY_STATUS[status] ?? fallback(status);
}
export function inflowStatusMeta(status: string): StatusMeta {
  return INFLOW_STATUS[status] ?? fallback(status);
}
export function alertTypeLabel(alertType: string): string {
  return ALERT_TYPE_LABEL[alertType] ?? alertType;
}
