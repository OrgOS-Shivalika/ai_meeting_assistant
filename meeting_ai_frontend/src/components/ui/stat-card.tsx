import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Two stat treatments from the system:
 *
 * - `StatCard` — the saturated 24px-radius feature tile. Colours cycle
 *   across a row so no two neighbours repeat a hue.
 * - `MetricCard` — the quiet cream/hairline variant for dense KPI grids,
 *   where a row of saturated tiles would shout.
 *
 * Numbers are always mono: the DS treats data as proof.
 */

/** Fills for the feature-tile cycle, in order. `fg` flips for dark fills. */
const FEATURE_FILLS = [
  { bg: "var(--vb-pink)", fg: "#fff", chip: "rgba(255,255,255,0.2)", sub: "rgba(255,255,255,0.9)" },
  { bg: "var(--vb-peach)", fg: "var(--vb-ink)", chip: "rgba(0,0,0,0.08)", sub: "var(--vb-body)" },
  { bg: "var(--vb-lavender)", fg: "var(--vb-ink)", chip: "rgba(0,0,0,0.08)", sub: "var(--vb-body)" },
  { bg: "var(--vb-surface-dark)", fg: "#fff", chip: "rgba(255,255,255,0.12)", sub: "rgba(255,255,255,0.7)" },
  { bg: "var(--vb-ochre)", fg: "var(--vb-ink)", chip: "rgba(0,0,0,0.08)", sub: "var(--vb-body)" },
  { bg: "var(--vb-mint)", fg: "var(--vb-ink)", chip: "rgba(0,0,0,0.08)", sub: "var(--vb-body)" },
] as const;

export interface StatCardProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: LucideIcon;
  value: React.ReactNode;
  label: React.ReactNode;
  /** Small figure in the top-right — a delta, share or count. */
  delta?: React.ReactNode;
  /** Position in the colour cycle. */
  tone?: number;
}

function StatCard({
  icon: Icon,
  value,
  label,
  delta,
  tone = 0,
  className,
  style,
  ...props
}: StatCardProps) {
  const fill = FEATURE_FILLS[tone % FEATURE_FILLS.length];
  return (
    <div
      className={cn("rounded-2xl p-6", className)}
      style={{ background: fill.bg, color: fill.fg, ...style }}
      {...props}
    >
      <div className="mb-5 flex items-center justify-between">
        {Icon ? (
          <span
            className="inline-flex size-[38px] items-center justify-center rounded-[11px]"
            style={{ background: fill.chip }}
          >
            <Icon className="size-[18px]" />
          </span>
        ) : (
          <span />
        )}
        {delta !== undefined && (
          <span
            className="text-xs font-semibold"
            style={{ color: fill.sub }}
          >
            {delta}
          </span>
        )}
      </div>
      <div className="font-mono text-[32px] leading-none font-medium">{value}</div>
      <div className="mt-2 text-[13px] opacity-85">{label}</div>
    </div>
  );
}

export interface MetricCardProps extends React.HTMLAttributes<HTMLDivElement> {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Tints just the number — used for done / at-risk style KPIs. */
  valueColor?: string;
  hint?: React.ReactNode;
  icon?: LucideIcon;
}

function MetricCard({
  label,
  value,
  valueColor,
  hint,
  icon: Icon,
  className,
  ...props
}: MetricCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-hairline bg-canvas p-[22px]",
        className,
      )}
      {...props}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-[13px] text-muted-ink">{label}</div>
        {Icon && <Icon className="size-4 text-muted-soft" />}
      </div>
      <div
        className="mt-2 font-mono text-[30px] leading-none font-medium text-ink"
        style={valueColor ? { color: valueColor } : undefined}
      >
        {value}
      </div>
      {hint && <div className="mt-2 text-xs text-muted-ink">{hint}</div>}
    </div>
  );
}

export { StatCard, MetricCard, FEATURE_FILLS };
