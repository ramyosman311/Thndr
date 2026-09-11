import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PnLBadge } from "@/components/ui/pnl-badge";

describe("PnLBadge", () => {
  it("communicates a profit with an explicit sign, arrow, and meaning — not color alone", () => {
    render(<PnLBadge value="100.00" percent="10.00" currency="EGP" />);
    expect(screen.getByText("↑")).toBeInTheDocument();
    expect(screen.getByText(/\+100\.00 EGP \(10\.00%\)/)).toBeInTheDocument();
    expect(screen.getByText(/ربح غير محقق/)).toBeInTheDocument();
  });

  it("communicates a loss with an explicit sign, arrow, and meaning", () => {
    render(<PnLBadge value="-100.00" percent="-10.00" currency="EGP" />);
    expect(screen.getByText("↓")).toBeInTheDocument();
    expect(screen.getByText(/-100\.00 EGP \(-10\.00%\)/)).toBeInTheDocument();
    expect(screen.getByText(/خسارة غير محققة/)).toBeInTheDocument();
  });

  it("communicates zero as no change, with no invented sign", () => {
    render(<PnLBadge value="0.00" currency="EGP" />);
    expect(screen.getByText("→")).toBeInTheDocument();
    expect(screen.getByText(/بدون تغيير/)).toBeInTheDocument();
  });

  it("uses realized wording when kind='realized'", () => {
    render(<PnLBadge value="50.00" currency="EGP" kind="realized" />);
    expect(screen.getByText(/ربح محقق/)).toBeInTheDocument();
  });

  it("never fabricates a value when null", () => {
    render(<PnLBadge value={null} />);
    expect(screen.getByText("غير متاح")).toBeInTheDocument();
  });
});
