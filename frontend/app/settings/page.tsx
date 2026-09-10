"use client";

import { useState } from "react";
import { PortfolioSettings } from "@/components/settings/portfolio-settings";
import { AssetsAdmin } from "@/components/settings/assets-admin";
import { StrategyAdmin } from "@/components/settings/strategy-admin";
import { PricingAdmin } from "@/components/settings/pricing-admin";

type SettingsTab = "portfolio" | "assets" | "strategy" | "pricing";

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "portfolio", label: "المحفظة" },
  { id: "assets", label: "الأصول" },
  { id: "strategy", label: "الاستراتيجية" },
  { id: "pricing", label: "الأسعار" },
];

export default function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>("portfolio");

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold text-foreground">الإعدادات</h1>

      <div role="tablist" aria-label="أقسام الإعدادات" className="flex gap-1.5 overflow-x-auto pb-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "portfolio" ? <PortfolioSettings /> : null}
      {tab === "assets" ? <AssetsAdmin /> : null}
      {tab === "strategy" ? <StrategyAdmin /> : null}
      {tab === "pricing" ? <PricingAdmin /> : null}
    </div>
  );
}
