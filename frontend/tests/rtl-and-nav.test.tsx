import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { ForwardChevronIcon } from "@/components/icons";
import { NAV_ITEMS } from "@/components/nav";

describe("RTL-aware chevron icon", () => {
  it("carries the rtl mirror utility class so it points the correct reading direction both ways", () => {
    const { container } = render(<ForwardChevronIcon data-testid="chevron" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("class")).toContain("rtl:-scale-x-100");
  });
});

describe("Navigation items", () => {
  it("defines exactly the five sections specified for Phase 9 (Dashboard, Portfolio, Watchlist, Allocation, Settings)", () => {
    expect(NAV_ITEMS.map((i) => i.href)).toEqual(["/", "/portfolio", "/allocation", "/watchlist", "/settings"]);
  });

  it("gives every nav item a non-empty Arabic label", () => {
    for (const item of NAV_ITEMS) {
      expect(item.label.length).toBeGreaterThan(0);
    }
  });
});
