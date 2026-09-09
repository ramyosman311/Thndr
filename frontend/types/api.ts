/**
 * Types mirroring the backend Pydantic schemas exactly (see
 * backend/app/schemas/*.py). `DecimalStr` fields serialize as JSON
 * strings (never numbers) so exact Decimal precision survives the API
 * boundary — see FINANCIAL_RULES.md, "Precision". The frontend must
 * never parse these into `number` for calculation, only for display
 * formatting (see lib/format.ts).
 */

/** A Decimal serialized as a string, e.g. "1234.56". */
export type DecimalStr = string;

// --- Portfolio (Phase 5) ----------------------------------------------

export interface HoldingPnLOut {
  asset_id: string;
  symbol: string;
  quantity: DecimalStr;
  average_cost: DecimalStr;
  current_price: DecimalStr;
  market_value: DecimalStr;
  cost_basis: DecimalStr;
  unrealized_pnl: DecimalStr;
  unrealized_pnl_percent: DecimalStr | null;
}

export interface PortfolioSummaryOut {
  base_currency: string;
  total_value: DecimalStr;
  emergency_value: DecimalStr;
  investable_value: DecimalStr;
  denominator_basis: string;
  denominator_value: DecimalStr;
  emergency_excluded: boolean;
  holdings_pnl: HoldingPnLOut[];
  /** Aggregated across holdings_pnl by the backend (Phase 9 addition to
   * PortfolioSummaryOut) — never recompute this client-side. */
  total_unrealized_pnl: DecimalStr;
  total_unrealized_pnl_percent: DecimalStr | null;
}

export type TargetStatus = "NO_TARGET" | "UNDERWEIGHT" | "ON_TARGET" | "OVERWEIGHT";
export type MinimumStatus = "NO_MINIMUM" | "ABOVE_MINIMUM" | "MINIMUM_BREACHED";
export type MaximumStatus = "NO_MAXIMUM" | "WITHIN_MAXIMUM" | "MAXIMUM_BREACHED";

export interface BucketAllocationOut {
  strategy_bucket_id: string;
  bucket_name: string;
  actual_value: DecimalStr;
  total_portfolio_percent: DecimalStr;
  risk_allocation_percent: DecimalStr | null;
  target_percent: DecimalStr | null;
  minimum_percent: DecimalStr | null;
  maximum_percent: DecimalStr | null;
  allow_new_buy: boolean | null;
  target_status: TargetStatus;
  minimum_status: MinimumStatus;
  maximum_status: MaximumStatus;
  buy_allowed: boolean;
  excluded_from_risk_allocation: boolean;
}

export interface PortfolioAllocationOut {
  total_portfolio_value: DecimalStr;
  risk_denominator_basis: string;
  risk_denominator_value: DecimalStr;
  emergency_excluded: boolean;
  buckets: BucketAllocationOut[];
}

// --- Strategy Validation (Phase 6) -------------------------------------

export type StrategyValidationStatus =
  | "VALID"
  | "INCOMPLETE_TARGET_ALLOCATION"
  | "OVERALLOCATED_TARGET_ALLOCATION"
  | "EMPTY_CONFIGURATION"
  | "INVALID_TARGET_VALUE"
  | "INVALID_MIN_MAX_CONFIGURATION";

export interface AllocationRuleOut {
  strategy_bucket_id: string;
  bucket_name: string;
  target_percent: DecimalStr | null;
  minimum_percent: DecimalStr | null;
  maximum_percent: DecimalStr | null;
  allow_new_buy: boolean;
  priority: number;
}

export interface RuleFieldErrorOut {
  strategy_bucket_id: string;
  bucket_name: string;
  message: string;
}

export interface StrategyValidationOut {
  status: StrategyValidationStatus;
  is_valid: boolean;
  total_target_percent: DecimalStr;
  expected_target_percent: DecimalStr;
  explanation: string;
  target_rows: AllocationRuleOut[];
  maximum_only_rows: AllocationRuleOut[];
  excluded_emergency_rows: AllocationRuleOut[];
  field_errors: RuleFieldErrorOut[];
  priority_order: AllocationRuleOut[];
}

// --- Smart Inflow Allocator (Phase 7) -----------------------------------

export type InflowStatus =
  | "ELIGIBLE"
  | "TARGET_GAP"
  | "MAXIMUM_LIMIT"
  | "BUY_DISABLED"
  | "EMERGENCY_EXCLUDED"
  | "NO_TARGET"
  | "AT_TARGET"
  | "OVER_TARGET"
  | "NO_CAPACITY";

export interface InflowAllocateRequest {
  amount: DecimalStr;
}

export interface InflowRecommendationOut {
  strategy_bucket_id: string;
  bucket_name: string;
  current_value: DecimalStr;
  current_percent: DecimalStr | null;
  target_percent: DecimalStr | null;
  maximum_percent: DecimalStr | null;
  allow_new_buy: boolean | null;
  priority: number;
  target_gap: DecimalStr | null;
  maximum_capacity: DecimalStr | null;
  eligible: boolean;
  allocated_amount: DecimalStr;
  status: InflowStatus;
  projected_value: DecimalStr | null;
  projected_percent: DecimalStr | null;
}

export interface InflowAllocationOut {
  requested_cash: DecimalStr;
  allocated_cash: DecimalStr;
  unallocated_cash: DecimalStr;
  strategy_status: StrategyValidationStatus;
  strategy_is_valid: boolean;
  recommendations: InflowRecommendationOut[];
}

// --- Watchlist + Alerts (Phase 8) ---------------------------------------

export interface AlertRuleOut {
  id: string;
  watchlist_id: string;
  enabled: boolean;
  allocation_alert_enabled: boolean;
  allocation_max_percent: DecimalStr | null;
  price_target_enabled: boolean;
  price_target: DecimalStr | null;
  dip_buy_enabled: boolean;
  dip_buy_price: DecimalStr | null;
  telegram_enabled: boolean;
  last_triggered_at: string | null;
}

export interface AlertRuleCreateRequest {
  enabled?: boolean;
  allocation_alert_enabled?: boolean;
  allocation_max_percent?: DecimalStr | null;
  price_target_enabled?: boolean;
  price_target?: DecimalStr | null;
  dip_buy_enabled?: boolean;
  dip_buy_price?: DecimalStr | null;
  telegram_enabled?: boolean;
}

export type AlertRuleUpdateRequest = Partial<AlertRuleCreateRequest>;

export interface WatchlistOut {
  id: string;
  asset_id: string;
  asset_symbol: string;
  enabled: boolean;
  notes: string | null;
  added_at: string;
  removed_at: string | null;
  alert_rule: AlertRuleOut | null;
}

export interface WatchlistAddRequest {
  asset_id: string;
  notes?: string | null;
}

export interface WatchlistUpdateRequest {
  enabled?: boolean;
  notes?: string | null;
}

export type AlertType =
  | "ALLOCATION_BREACH"
  | "PRICE_TARGET"
  | "DIP_BUY"
  | "REBALANCE_SUGGESTED"
  | "INCOME_MATURITY";

export interface AlertEvaluationEntryOut {
  alert_rule_id: string;
  watchlist_id: string;
  asset_symbol: string;
  alert_type: AlertType;
  condition_met: boolean;
  is_new_trigger: boolean;
  should_clear: boolean;
  reason: string;
  current_value: DecimalStr | null;
  threshold_value: DecimalStr | null;
}

export interface AlertEvaluationOut {
  results: AlertEvaluationEntryOut[];
}

// --- Assets (Phase 9 read-only listing) ----------------------------------

export interface AssetOut {
  id: string;
  symbol: string;
  name: string;
  asset_type: string;
  currency: string;
  is_active: boolean;
}

// --- Health --------------------------------------------------------------

export interface HealthOut {
  status: string;
  database: string;
}
