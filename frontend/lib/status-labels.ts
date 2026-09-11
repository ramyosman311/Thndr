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

export const PRICE_STATUS: Record<string, StatusMeta> = {
  CURRENT_PRICE_AVAILABLE: { label: "سعر مباشر", tone: "success" },
  LAST_KNOWN_PRICE: { label: "آخر سعر معروف", tone: "warning" },
  PRICE_UNAVAILABLE: { label: "السعر غير متاح", tone: "neutral" },
  CURRENCY_CONVERSION_UNAVAILABLE: { label: "تعذّر تحويل العملة", tone: "danger" },
  // Phase 16: the Portfolio Summary's simpler two-value price-confidence
  // field (see types/api.ts, PriceConfidence) — shares this same label
  // map/badge component rather than a separate one.
  LIVE: { label: "سعر مباشر", tone: "success" },
  PENDING_SYNC: { label: "بانتظار مزامنة السعر", tone: "warning" },
};

// Phase 17: Smart Rebalancing Engine's action verb — a NEW, small
// vocabulary distinct from TARGET_STATUS/MAXIMUM_STATUS above (which are
// shown separately as the underlying category state).
export const REBALANCING_ACTION: Record<string, StatusMeta> = {
  BUY: { label: "شراء موصى به", tone: "success" },
  REDUCE: { label: "تخفيض موصى به", tone: "danger" },
  HOLD: { label: "لا إجراء", tone: "neutral" },
  NO_CAPACITY: { label: "لا سيولة متاحة", tone: "warning" },
  NO_TARGET: { label: "قيد فقط، بدون توصية", tone: "neutral" },
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
export function priceStatusMeta(status: string): StatusMeta {
  return PRICE_STATUS[status] ?? fallback(status);
}
export function rebalancingActionMeta(action: string): StatusMeta {
  return REBALANCING_ACTION[action] ?? fallback(action);
}

// Phase 18: Smart Recommendations severity -> visual tone only. The
// title/message text itself is already natural Arabic returned by the
// backend (domain/recommendation_engine.py) — this map never supplies
// display text, only color.
export const RECOMMENDATION_SEVERITY_TONE: Record<string, Tone> = {
  CRITICAL: "danger",
  WARNING: "warning",
  INFO: "info",
  SUCCESS: "success",
};

export function recommendationSeverityTone(severity: string): Tone {
  return RECOMMENDATION_SEVERITY_TONE[severity] ?? "neutral";
}
