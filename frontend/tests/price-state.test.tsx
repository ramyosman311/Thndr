import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mocks = vi.hoisted(() => ({
  setManualPrice: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { ...actual.api, setManualPrice: mocks.setManualPrice },
  };
});

import { ManualPriceEditor, PriceStateBadge } from "@/components/portfolio/price-state";

describe("PriceStateBadge", () => {
  it("shows a live-price label with a relative-time caption for a current price", () => {
    render(
      <PriceStateBadge status="CURRENT_PRICE_AVAILABLE" isStale={false} recordedAt={new Date().toISOString()} />
    );
    expect(screen.getByText("سعر مباشر")).toBeInTheDocument();
    expect(screen.getByText(/تحديث/)).toBeInTheDocument();
  });

  it("visually distinguishes a stale/last-known price from a live one", () => {
    render(
      <PriceStateBadge
        status="LAST_KNOWN_PRICE"
        isStale={true}
        recordedAt={new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString()}
      />
    );
    expect(screen.getByText("آخر سعر معروف")).toBeInTheDocument();
    expect(screen.queryByText("سعر مباشر")).not.toBeInTheDocument();
  });

  it("never presents an unavailable price as if it were live, and shows no fabricated age", () => {
    render(<PriceStateBadge status="PRICE_UNAVAILABLE" isStale={false} recordedAt={null} />);
    expect(screen.getByText("السعر غير متاح")).toBeInTheDocument();
    expect(screen.queryByText(/تحديث/)).not.toBeInTheDocument();
  });

  it("shows a distinct label for currency-conversion-unavailable", () => {
    render(<PriceStateBadge status="CURRENCY_CONVERSION_UNAVAILABLE" isStale={false} recordedAt={null} />);
    expect(screen.getByText("تعذّر تحويل العملة")).toBeInTheDocument();
  });
});

describe("ManualPriceEditor", () => {
  it("submits the manual price in the asset's own currency, never the portfolio's display currency", async () => {
    mocks.setManualPrice.mockResolvedValue({ status: "CURRENT_PRICE_AVAILABLE" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<ManualPriceEditor assetId="asset-1" assetCurrency="USD" onSaved={onSaved} />);

    await user.click(screen.getByRole("button", { name: "تعديل السعر يدويًا" }));
    const input = screen.getByPlaceholderText("السعر بعملة USD");
    await user.type(input, "42.50");
    await user.click(screen.getByRole("button", { name: "حفظ" }));

    await waitFor(() => {
      expect(mocks.setManualPrice).toHaveBeenCalledWith("asset-1", { price: "42.50", currency: "USD" });
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("rejects a non-positive price without calling the API", async () => {
    const user = userEvent.setup();
    render(<ManualPriceEditor assetId="asset-1" assetCurrency="EGP" onSaved={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "تعديل السعر يدويًا" }));
    await user.type(screen.getByPlaceholderText("السعر بعملة EGP"), "0");
    await user.click(screen.getByRole("button", { name: "حفظ" }));

    expect(await screen.findByText(/أدخل سعرًا صحيحًا/)).toBeInTheDocument();
    expect(mocks.setManualPrice).not.toHaveBeenCalled();
  });

  it("never alters the form for anything except this asset's own price", () => {
    render(<ManualPriceEditor assetId="asset-1" assetCurrency="EGP" onSaved={vi.fn()} />);
    // The collapsed state is a single pencil button — no transaction/quantity fields exist here at all.
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "تعديل السعر يدويًا" })).toBeInTheDocument();
  });
});
