"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BellIcon, HomeIcon, PieChartIcon, SettingsIcon, WalletIcon } from "@/components/icons";
import type { ComponentType, SVGProps } from "react";

interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "الرئيسية", icon: HomeIcon },
  { href: "/portfolio", label: "المحفظة", icon: WalletIcon },
  { href: "/allocation", label: "التوزيع", icon: PieChartIcon },
  { href: "/watchlist", label: "المتابعة", icon: BellIcon },
  { href: "/settings", label: "الإعدادات", icon: SettingsIcon },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Mobile-first bottom tab bar — the primary navigation on small
 * screens, hidden from md upward in favor of TopNav. */
export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="التنقل الرئيسي"
      className="safe-bottom safe-x fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 backdrop-blur md:hidden"
    >
      <ul className="mx-auto flex max-w-lg items-stretch justify-between px-1">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          const Icon = item.icon;
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center gap-1 px-1 py-2.5 text-[11px] font-medium transition-colors ${
                  active ? "text-primary" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Icon aria-hidden="true" />
                <span>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Desktop/tablet top navigation — same items, horizontal, visible from
 * md upward. Built for the same IA rather than a separate desktop-first
 * design (see Phase 9 "mobile-first" requirement). */
export function TopNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="التنقل الرئيسي" className="hidden md:flex md:items-center md:gap-1">
      {NAV_ITEMS.map((item) => {
        const active = isActive(pathname, item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
              active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon width={16} height={16} aria-hidden="true" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
