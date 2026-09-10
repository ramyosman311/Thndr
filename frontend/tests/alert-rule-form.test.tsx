import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mocks = vi.hoisted(() => ({
  createWatchlistAlertRule: vi.fn(),
  updateAlertRule: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { ...mocks },
  };
});

import { AlertRuleForm } from "@/components/watchlist/alert-rule-form";

describe("AlertRuleForm", () => {
  it("includes telegram_enabled=false by default when creating a rule", async () => {
    mocks.createWatchlistAlertRule.mockResolvedValue({
      id: "r1", watchlist_id: "w1", enabled: true, allocation_alert_enabled: false,
      allocation_max_percent: null, price_target_enabled: true, price_target: "150.00",
      dip_buy_enabled: false, dip_buy_price: null, telegram_enabled: false, last_triggered_at: null,
    });

    const user = userEvent.setup();
    render(<AlertRuleForm watchlistId="w1" existing={null} onSaved={() => {}} />);

    await user.click(screen.getByLabelText("تنبيه عند سعر مستهدف"));
    await user.type(screen.getByPlaceholderText("السعر المستهدف"), "150");
    await user.click(screen.getByRole("button", { name: "إنشاء قاعدة التنبيه" }));

    await waitFor(() =>
      expect(mocks.createWatchlistAlertRule).toHaveBeenCalledWith(
        "w1",
        expect.objectContaining({ telegram_enabled: false })
      )
    );
  });

  it("toggles telegram_enabled on and includes it in the update payload", async () => {
    const existing = {
      id: "r1", watchlist_id: "w1", enabled: true, allocation_alert_enabled: false,
      allocation_max_percent: null, price_target_enabled: true, price_target: "150.00",
      dip_buy_enabled: false, dip_buy_price: null, telegram_enabled: false, last_triggered_at: null,
    };
    mocks.updateAlertRule.mockResolvedValue({ ...existing, telegram_enabled: true });

    const user = userEvent.setup();
    render(<AlertRuleForm watchlistId="w1" existing={existing} onSaved={() => {}} />);

    await user.click(screen.getByLabelText("إرسال تنبيه عبر تيليجرام"));
    await user.click(screen.getByRole("button", { name: "حفظ التعديلات" }));

    await waitFor(() =>
      expect(mocks.updateAlertRule).toHaveBeenCalledWith(
        "r1",
        expect.objectContaining({ telegram_enabled: true })
      )
    );
  });
});
