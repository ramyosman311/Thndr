"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";

/** Cycles light -> dark -> system. Renders nothing meaningful until
 * mounted, to avoid a hydration mismatch between server and the
 * user's persisted preference (next-themes' documented pattern). */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Documented next-themes pattern: the persisted theme is only known
  // client-side, so this flips once after mount to avoid a
  // server/client hydration mismatch — not state derived from props.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time mount flag, not a cascading update
    setMounted(true);
  }, []);

  const labels: Record<string, string> = {
    light: "فاتح",
    dark: "داكن",
    system: "تلقائي",
  };

  const next: Record<string, string> = {
    light: "dark",
    dark: "system",
    system: "light",
  };

  const icon: Record<string, string> = {
    light: "☀️",
    dark: "🌙",
    system: "🖥️",
  };

  const current = mounted ? theme ?? "system" : "system";

  return (
    <button
      type="button"
      onClick={() => setTheme(next[current] ?? "system")}
      aria-label={`تبديل المظهر، الحالي: ${labels[current]}`}
      className="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
    >
      <span aria-hidden="true">{icon[current]}</span>
      <span>{labels[current]}</span>
    </button>
  );
}
