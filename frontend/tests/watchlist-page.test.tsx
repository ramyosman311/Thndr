import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mocks = vi.hoisted(() => ({
  listWatchlist: vi.fn(),
  listAssets: vi.fn(),
  addWatchlistEntry: vi.fn(),
  removeWatchlistEntry: vi.fn(),
  updateWatchlistEntry: vi.fn(),
  evaluateAlerts: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listWatchlist: mocks.listWatchlist,
      listAssets: mocks.listAssets,
      addWatchlistEntry: mocks.addWatchlistEntry,
      removeWatchlistEntry: mocks.removeWatchlistEntry,
      updateWatchlistEntry: mocks.updateWatchlistEntry,
      evaluateAlerts: mocks.evaluateAlerts,
    },
  };
});

import WatchlistPage from "@/app/watchlist/page";

const ASSET = { id: "a1", symbol: "TMGH", name: "TMG Holding", asset_type: "STOCK", currency: "EGP", is_active: true };

describe("WatchlistPage", () => {
  it("adds an asset to the watchlist and shows it in the list", async () => {
    mocks.listWatchlist.mockResolvedValue([]);
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.addWatchlistEntry.mockResolvedValue({
      id: "w1",
      asset_id: "a1",
      asset_symbol: "TMGH",
      enabled: true,
      notes: null,
      added_at: "2026-01-01T00:00:00Z",
      removed_at: null,
      alert_rule: null,
    });

    const user = userEvent.setup();
    render(<WatchlistPage />);

    await waitFor(() => expect(screen.getByText("لا توجد أصول قيد المتابعة")).toBeInTheDocument());

    const select = await screen.findByRole("combobox");
    await user.selectOptions(select, "a1");
    await user.click(screen.getByRole("button", { name: "إضافة" }));

    await waitFor(() => {
      expect(mocks.addWatchlistEntry).toHaveBeenCalledWith({ asset_id: "a1", notes: null });
    });
    await waitFor(() => {
      expect(screen.getByText("TMGH")).toBeInTheDocument();
    });
  });

  it("removes a watchlist entry (logical removal) when the trash button is clicked", async () => {
    const entry = {
      id: "w1",
      asset_id: "a1",
      asset_symbol: "TMGH",
      enabled: true,
      notes: null,
      added_at: "2026-01-01T00:00:00Z",
      removed_at: null,
      alert_rule: null,
    };
    mocks.listWatchlist.mockResolvedValue([entry]);
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.removeWatchlistEntry.mockResolvedValue({ ...entry, enabled: false, removed_at: "2026-01-02T00:00:00Z" });

    const user = userEvent.setup();
    render(<WatchlistPage />);

    await waitFor(() => expect(screen.getByText("TMGH")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /إزالة TMGH من المتابعة/ }));

    await waitFor(() => {
      expect(mocks.removeWatchlistEntry).toHaveBeenCalledWith("w1");
    });
  });

  it("displays alert evaluation results without executing any trade", async () => {
    mocks.listWatchlist.mockResolvedValue([]);
    mocks.listAssets.mockResolvedValue([]);
    mocks.evaluateAlerts.mockResolvedValue({
      results: [
        {
          alert_rule_id: "r1",
          watchlist_id: "w1",
          asset_symbol: "TMGH",
          alert_type: "PRICE_TARGET",
          condition_met: true,
          is_new_trigger: true,
          should_clear: false,
          reason: "price 150 >= target 150",
          current_value: "150.00",
          threshold_value: "150.00",
        },
      ],
    });

    const user = userEvent.setup();
    render(<WatchlistPage />);

    await user.click(screen.getByRole("button", { name: "تقييم التنبيهات الآن" }));

    await waitFor(() => {
      expect(screen.getByText(/TMGH — سعر مستهدف/)).toBeInTheDocument();
    });
    expect(screen.getByText("جديد")).toBeInTheDocument();
    // The panel may legitimately reassure "no sell/buy is executed", but
    // must never claim one WAS executed.
    expect(screen.queryByText(/تم البيع|تم الشراء/)).not.toBeInTheDocument();
  });
});
