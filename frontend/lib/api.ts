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
  AssetOut,
  HealthOut,
  InflowAllocationOut,
  PortfolioAllocationOut,
  PortfolioSummaryOut,
  StrategyValidationOut,
  WatchlistAddRequest,
  WatchlistOut,
  WatchlistUpdateRequest,
} from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

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

function kindForStatus(status: number): ApiErrorKind {
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

  listAssets: () => request<AssetOut[]>("/assets"),

  portfolioSummary: () => request<PortfolioSummaryOut>("/portfolio/summary"),
  portfolioAllocation: () => request<PortfolioAllocationOut>("/portfolio/allocation"),
  strategyValidation: () => request<StrategyValidationOut>("/portfolio/strategy/validation"),

  allocateCashFlow: (amount: string) =>
    request<InflowAllocationOut>("/cash-flow/allocate", {
      method: "POST",
      body: JSON.stringify({ amount }),
    }),

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
};
