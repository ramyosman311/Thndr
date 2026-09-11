/**
 * Centralized, typed API client for the FastAPI backend. No component
 * should call `fetch()` directly — see ARCHITECTURE.md, "Frontend
 * Layering" ("hooks call the backend API; they do not recompute
 * financial figures the backend already returns").
 */
import type {
  AlertEvaluationOut,
  AlertRuleCreateRequest,
  AlertRuleOut,
  AlertRuleUpdateRequest,
  AllocationTargetCreateRequest,
  AllocationTargetOut,
  AllocationTargetUpdateRequest,
  AnalyticsRange,
  AssetCreateRequest,
  AssetOut,
  AssetPriceConfigOut,
  AssetPriceConfigUpsertRequest,
  AssetUpdateRequest,
  HealthOut,
  InflowAllocationOut,
  PortfolioAnalyticsHistoryOut,
  ManualPriceCreateRequest,
  PortfolioAllocationOut,
  PortfolioConfigCreateRequest,
  PortfolioConfigOut,
  PortfolioConfigUpdateRequest,
  PortfolioSummaryOut,
  PriceObservationOut,
  PriceOut,
  RebalancingOut,
  StrategyBucketCreateRequest,
  StrategyBucketOut,
  StrategyBucketUpdateRequest,
  StrategyValidationOut,
  TransactionCreateRequest,
  TransactionOut,
  TransactionResultOut,
  WatchlistAddRequest,
  WatchlistOut,
  WatchlistUpdateRequest,
} from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

export type ApiErrorKind = "not_configured" | "validation" | "conflict" | "not_found" | "server" | "network";

/** A typed, discriminated API failure. Never a raw stack trace: the
 * backend's global exception handler already redacts those (see
 * app/main.py), and this class preserves only `detail` and status. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly detail: string;

  constructor(kind: ApiErrorKind, status: number | null, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

export function kindForStatus(status: number): ApiErrorKind {
  if (status === 400) return "validation";
  if (status === 404) return "not_configured";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status >= 500) return "server";
  return "server";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("network", null, "تعذّر الوصول إلى الخادم. تحقق من الاتصال بالشبكة.");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body && typeof (body as { detail?: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : "حدث خطأ غير متوقع.";
    throw new ApiError(kindForStatus(response.status), response.status, detail);
  }

  return body as T;
}

export const api = {
  health: () => request<HealthOut>("/health"),

  listAssets: (includeInactive = false) =>
    request<AssetOut[]>(`/assets${includeInactive ? "?include_inactive=true" : ""}`),
  getAsset: (assetId: string) => request<AssetOut>(`/assets/${assetId}`),
  createAsset: (payload: AssetCreateRequest) =>
    request<AssetOut>("/assets", { method: "POST", body: JSON.stringify(payload) }),
  updateAsset: (assetId: string, payload: AssetUpdateRequest) =>
    request<AssetOut>(`/assets/${assetId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  activateAsset: (assetId: string) => request<AssetOut>(`/assets/${assetId}/activate`, { method: "POST" }),
  deactivateAsset: (assetId: string) => request<AssetOut>(`/assets/${assetId}/deactivate`, { method: "POST" }),
  deleteAsset: (assetId: string) => request<void>(`/assets/${assetId}`, { method: "DELETE" }),

  portfolioSummary: () => request<PortfolioSummaryOut>("/portfolio/summary"),
  portfolioAllocation: () => request<PortfolioAllocationOut>("/portfolio/allocation"),
  portfolioRebalancing: () => request<RebalancingOut>("/portfolio/rebalancing"),
  strategyValidation: () => request<StrategyValidationOut>("/portfolio/strategy/validation"),

  portfolioAnalyticsHistory: (range: AnalyticsRange) =>
    request<PortfolioAnalyticsHistoryOut>(`/portfolio/analytics/history?range=${range}`),

  getPortfolioConfig: () => request<PortfolioConfigOut>("/portfolio/config"),
  createPortfolioConfig: (payload: PortfolioConfigCreateRequest) =>
    request<PortfolioConfigOut>("/portfolio/config", { method: "POST", body: JSON.stringify(payload) }),
  updatePortfolioConfig: (payload: PortfolioConfigUpdateRequest) =>
    request<PortfolioConfigOut>("/portfolio/config", { method: "PATCH", body: JSON.stringify(payload) }),

  listStrategyBuckets: (includeInactive = false) =>
    request<StrategyBucketOut[]>(`/strategy/buckets${includeInactive ? "?include_inactive=true" : ""}`),
  createStrategyBucket: (payload: StrategyBucketCreateRequest) =>
    request<StrategyBucketOut>("/strategy/buckets", { method: "POST", body: JSON.stringify(payload) }),
  updateStrategyBucket: (bucketId: string, payload: StrategyBucketUpdateRequest) =>
    request<StrategyBucketOut>(`/strategy/buckets/${bucketId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  activateStrategyBucket: (bucketId: string) =>
    request<StrategyBucketOut>(`/strategy/buckets/${bucketId}/activate`, { method: "POST" }),
  deactivateStrategyBucket: (bucketId: string) =>
    request<StrategyBucketOut>(`/strategy/buckets/${bucketId}/deactivate`, { method: "POST" }),

  listAllocationTargets: (includeInactive = false) =>
    request<AllocationTargetOut[]>(`/strategy/targets${includeInactive ? "?include_inactive=true" : ""}`),
  createAllocationTarget: (payload: AllocationTargetCreateRequest) =>
    request<AllocationTargetOut>("/strategy/targets", { method: "POST", body: JSON.stringify(payload) }),
  updateAllocationTarget: (targetId: string, payload: AllocationTargetUpdateRequest) =>
    request<AllocationTargetOut>(`/strategy/targets/${targetId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  allocateCashFlow: (amount: string) =>
    request<InflowAllocationOut>("/cash-flow/allocate", {
      method: "POST",
      body: JSON.stringify({ amount }),
    }),

  createTransaction: (payload: TransactionCreateRequest) =>
    request<TransactionResultOut>("/transactions", { method: "POST", body: JSON.stringify(payload) }),
  listTransactions: () => request<TransactionOut[]>("/transactions"),

  listWatchlist: (enabledOnly = false) =>
    request<WatchlistOut[]>(`/watchlist${enabledOnly ? "?enabled_only=true" : ""}`),
  addWatchlistEntry: (payload: WatchlistAddRequest) =>
    request<WatchlistOut>("/watchlist", { method: "POST", body: JSON.stringify(payload) }),
  updateWatchlistEntry: (id: string, payload: WatchlistUpdateRequest) =>
    request<WatchlistOut>(`/watchlist/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  removeWatchlistEntry: (id: string) => request<WatchlistOut>(`/watchlist/${id}`, { method: "DELETE" }),

  getWatchlistAlertRule: (watchlistId: string) => request<AlertRuleOut>(`/watchlist/${watchlistId}/alerts`),
  createWatchlistAlertRule: (watchlistId: string, payload: AlertRuleCreateRequest) =>
    request<AlertRuleOut>(`/watchlist/${watchlistId}/alerts`, { method: "POST", body: JSON.stringify(payload) }),
  updateAlertRule: (alertRuleId: string, payload: AlertRuleUpdateRequest) =>
    request<AlertRuleOut>(`/alerts/${alertRuleId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAlertRule: (alertRuleId: string) => request<void>(`/alerts/${alertRuleId}`, { method: "DELETE" }),
  evaluateAlerts: () => request<AlertEvaluationOut>("/alerts/evaluate", { method: "POST" }),

  getAssetPrice: (assetId: string) => request<PriceOut>(`/assets/${assetId}/price`),
  listAssetPrices: (assetId: string) => request<PriceObservationOut[]>(`/assets/${assetId}/prices`),
  setManualPrice: (assetId: string, payload: ManualPriceCreateRequest) =>
    request<PriceOut>(`/assets/${assetId}/price/manual`, { method: "POST", body: JSON.stringify(payload) }),
  refreshAssetPrice: (assetId: string) =>
    request<PriceOut>(`/assets/${assetId}/price/refresh`, { method: "POST" }),

  getAssetPriceConfig: (assetId: string) => request<AssetPriceConfigOut>(`/assets/${assetId}/price-config`),
  putAssetPriceConfig: (assetId: string, payload: AssetPriceConfigUpsertRequest) =>
    request<AssetPriceConfigOut>(`/assets/${assetId}/price-config`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};
