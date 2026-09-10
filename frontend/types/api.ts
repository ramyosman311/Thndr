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

/** Phase 11: matches domain/price_types.py's PriceStatus exactly. */
export type PriceStatus =
  | "CURRENT_PRICE_AVAILABLE"
  | "LAST_KNOWN_PRICE"
  | "PRICE_UNAVAILABLE"
  | "CURRENCY_CONVERSION_UNAVAILABLE";

export interface HoldingPnLOut {
  asset_id: string;
  symbol: string;
  quantity: DecimalStr;
  average_cost: DecimalStr;
  /** The asset's OWN currency — a manual price submission must use
   * this, not the portfolio's base_currency `current_price` is shown
   * in below. */
  asset_currency: string;
  /** Phase 11: null when the Price Service has no usable price — never
   * a fabricated 0. Never render this as "0.00"; use `price_status`. */
  current_price: DecimalStr | null;
  price_status: PriceStatus;
  price_recorded_at: string | null;
  price_is_stale: boolean;
  market_value: DecimalStr | null;
  cost_basis: DecimalStr | null;
  unrealized_pnl: DecimalStr | null;
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
  /** Phase 11: False when at least one held asset had no usable price —
   * the totals above EXCLUDE that asset's value rather than treating it
   * as 0. See `unpriced_asset_ids`. */
  is_complete: boolean;
  unpriced_asset_ids: string[];
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
  /** Phase 11: True when this bucket's actual_value excludes at least
   * one held-but-unpriced position. */
  has_unpriced_positions: boolean;
}

export interface PortfolioAllocationOut {
  total_portfolio_value: DecimalStr;
  risk_denominator_basis: string;
  risk_denominator_value: DecimalStr;
  emergency_excluded: boolean;
  is_complete: boolean;
  unpriced_asset_ids: string[];
  buckets: BucketAllocationOut[];
}

// --- Portfolio Configuration administration (Phase 12) -------------------

export interface PortfolioConfigOut {
  id: string;
  name: string;
  base_currency: string;
  emergency_asset_id: string | null;
  emergency_excluded: boolean;
  telegram_enabled: boolean;
}

export interface PortfolioConfigCreateRequest {
  name: string;
  base_currency: string;
  emergency_asset_id?: string | null;
  emergency_excluded?: boolean;
}

export interface PortfolioConfigUpdateRequest {
  name?: string;
  base_currency?: string;
  emergency_asset_id?: string;
  clear_emergency_asset?: boolean;
  emergency_excluded?: boolean;
  telegram_enabled?: boolean;
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

// --- Strategy Bucket + Allocation Target administration (Phase 12) ------

export interface StrategyBucketOut {
  id: string;
  portfolio_config_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
}

export interface StrategyBucketCreateRequest {
  name: string;
  description?: string | null;
}

export interface StrategyBucketUpdateRequest {
  name?: string;
  description?: string | null;
}

export interface AllocationTargetOut {
  id: string;
  portfolio_config_id: string;
  strategy_bucket_id: string;
  target_percent: DecimalStr | null;
  minimum_percent: DecimalStr | null;
  maximum_percent: DecimalStr | null;
  allow_new_buy: boolean;
  priority: number;
  is_active: boolean;
}

export interface AllocationTargetCreateRequest {
  strategy_bucket_id: string;
  target_percent?: DecimalStr | null;
  minimum_percent?: DecimalStr | null;
  maximum_percent?: DecimalStr | null;
  allow_new_buy?: boolean;
  priority?: number;
}

export interface AllocationTargetUpdateRequest {
  target_percent?: DecimalStr;
  clear_target_percent?: boolean;
  minimum_percent?: DecimalStr;
  clear_minimum_percent?: boolean;
  maximum_percent?: DecimalStr;
  clear_maximum_percent?: boolean;
  allow_new_buy?: boolean;
  priority?: number;
  is_active?: boolean;
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
  is_complete: boolean;
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

// --- Transactions + Holdings (Phase 10) ----------------------------------

export type TransactionKind = "BUY" | "SELL";

export interface TransactionCreateRequest {
  asset_id: string;
  transaction_type: TransactionKind;
  quantity: DecimalStr;
  price: DecimalStr;
  fees?: DecimalStr;
  /** ISO-8601 datetime string. */
  transaction_date: string;
  notes?: string | null;
}

export interface TransactionOut {
  id: string;
  asset_id: string;
  asset_symbol: string;
  transaction_type: string;
  quantity: DecimalStr;
  price: DecimalStr;
  fees: DecimalStr;
  transaction_date: string;
  notes: string | null;
  created_at: string;
}

export interface HoldingSnapshotOut {
  quantity: DecimalStr;
  average_cost: DecimalStr;
  /** Phase 11: null when the Price Service has no usable price. */
  current_price: DecimalStr | null;
  price_status: PriceStatus;
}

export interface TransactionResultOut {
  transaction: TransactionOut;
  holding: HoldingSnapshotOut;
  /** Only present for SELL — see FINANCIAL_RULES.md, "Realized P/L". */
  realized_pnl: DecimalStr | null;
}

// --- Assets (Phase 9 read-only listing; Phase 12 administration) --------

/** Matches backend AssetType enum. Domain data, not a UI-invented list —
 * mirrors app/models/enums.py exactly. */
export type AssetType = "STOCK" | "FUND" | "GOLD" | "CASH" | "SAVINGS" | "ETF" | "OTHER";

export interface AssetOut {
  id: string;
  symbol: string;
  name: string;
  asset_type: string;
  market: string | null;
  currency: string;
  strategy_bucket_id: string | null;
  is_active: boolean;
}

export interface AssetCreateRequest {
  symbol: string;
  name: string;
  asset_type: AssetType;
  market?: string | null;
  currency: string;
  strategy_bucket_id?: string | null;
}

export interface AssetUpdateRequest {
  name?: string;
  asset_type?: AssetType;
  market?: string | null;
  currency?: string;
  strategy_bucket_id?: string;
  clear_strategy_bucket?: boolean;
}

// --- Prices (Phase 11) ----------------------------------------------------

export interface PriceOut {
  asset_id: string;
  status: PriceStatus;
  price: DecimalStr | null;
  currency: string | null;
  provider: string | null;
  provider_symbol: string | null;
  recorded_at: string | null;
  age_seconds: number | null;
  is_stale: boolean;
  reason: string | null;
}

export interface PriceObservationOut {
  id: string;
  price: DecimalStr;
  currency: string;
  provider: string;
  source: string | null;
  provider_symbol: string | null;
  recorded_at: string;
  is_manual: boolean;
}

export interface ManualPriceCreateRequest {
  price: DecimalStr;
  currency: string;
}

// --- Asset Price Configuration administration (Phase 12) -----------------

export interface AssetPriceConfigOut {
  asset_id: string;
  configured: boolean;
  primary_provider: string | null;
  primary_provider_symbol: string | null;
  secondary_provider: string | null;
  secondary_provider_symbol: string | null;
  automated_fetching_enabled: boolean;
  manual_override_enabled: boolean;
  stale_threshold_minutes: number | null;
  lock_manual: boolean;
}

export interface AssetPriceConfigUpsertRequest {
  primary_provider?: string | null;
  primary_provider_symbol?: string | null;
  secondary_provider?: string | null;
  secondary_provider_symbol?: string | null;
  automated_fetching_enabled?: boolean;
  manual_override_enabled?: boolean;
  stale_threshold_minutes?: number | null;
  lock_manual?: boolean;
}

// --- Health --------------------------------------------------------------

export interface HealthOut {
  status: string;
  database: string;
}
