import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Pill progress track on the cream ramp. `segments` renders a stacked bar
 * (done / active / at-risk) as on the board cards; `value` is the simple
 * single-hue case used in Reports.
 */
export interface ProgressSegment {
  /** Share of the track, 0–100. */
  value: number;
  color: string;
  label?: string;
}

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: number;
  color?: string;
  segments?: ProgressSegment[];
  size?: "sm" | "default" | "lg";
}

function Progress({
  value = 0,
  color = "var(--vb-info)",
  segments,
  size = "default",
  className,
  ...props
}: ProgressProps) {
  const parts = segments ?? [{ value, color }];
  return (
    <div
      role="progressbar"
      aria-valuenow={segments ? undefined : Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn(
        "flex overflow-hidden rounded-full bg-surface-card",
        size === "sm" && "h-1.5",
        size === "default" && "h-2",
        size === "lg" && "h-2.5",
        className,
      )}
      {...props}
    >
      {parts.map((part, index) => (
        <span
          key={index}
          title={part.label}
          style={{
            width: `${Math.max(0, Math.min(100, part.value))}%`,
            background: part.color,
          }}
        />
      ))}
    </div>
  );
}

export { Progress };
