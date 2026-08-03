import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * The pill segmented control from the Meetings filter bar: a cream track
 * with the active segment lifted onto the canvas. Each option may carry a
 * status dot in its own hue.
 */
export interface SegmentedOption<T extends string> {
  value: T;
  label: React.ReactNode;
  /** Any CSS colour; renders a 6px dot before the label. */
  dotColor?: string;
  count?: number | string;
}

export interface SegmentedProps<T extends string>
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "onChange"> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "default";
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "default",
  className,
  ...props
}: SegmentedProps<T>) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full bg-surface-card p-[3px]",
        className,
      )}
      {...props}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full transition-colors",
              size === "default" ? "px-3.5 py-[7px] text-xs" : "px-3 py-1.5 text-[11px]",
              active
                ? "bg-canvas font-semibold text-ink"
                : "font-medium text-muted-ink hover:text-body-strong",
            )}
          >
            {option.dotColor && (
              <span
                className="size-1.5 rounded-full"
                style={{ background: option.dotColor }}
                aria-hidden
              />
            )}
            {option.label}
            {option.count !== undefined && (
              <span className="font-mono text-[10px] opacity-70">{option.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Standalone filter pills (Browse templates, Tasks). Unlike `Segmented`
 * these sit directly on the canvas with a hairline, and the active pill
 * fills with ink.
 */
export interface FilterPillProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean;
  count?: number | string;
  /** Tints the pill with a semantic hue when it needs attention. */
  tone?: "default" | "warning" | "success" | "info";
}

function FilterPill({
  active,
  count,
  tone = "default",
  className,
  children,
  ...props
}: FilterPillProps) {
  const toned = tone !== "default";
  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-xs font-semibold transition-colors",
        active && !toned && "bg-ink text-on-ink",
        !active && !toned && "border border-hairline bg-canvas text-body hover:bg-surface-soft",
        tone === "warning" && "border border-warning/30 bg-warning/14 text-warning",
        tone === "success" && "border border-success/30 bg-success/12 text-success",
        tone === "info" && "border border-info/30 bg-info/12 text-info",
        className,
      )}
      {...props}
    >
      {children}
      {count !== undefined && (
        <span
          className={cn(
            "rounded-full px-[7px] py-px text-[11px]",
            active && !toned ? "bg-white/15" : "bg-surface-card",
            toned && "bg-current/15",
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}

export { Segmented, FilterPill };
