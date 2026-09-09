import type { Tone } from "@/lib/status-labels";

const TONE_CLASSES: Record<Tone, string> = {
  success: "bg-success-muted text-success",
  warning: "bg-warning-muted text-warning",
  danger: "bg-danger-muted text-danger",
  info: "bg-accent text-accent-foreground",
  neutral: "bg-muted text-muted-foreground",
};

export function StatusPill({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium leading-none ${TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  );
}
