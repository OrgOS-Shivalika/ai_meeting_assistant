import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * 44×26 track with a springy knob — the Settings toggle. Off is the cream
 * ramp, on is ink. Radix's switch package isn't vendored here, so this is
 * a plain `role="switch"` button with the same props surface.
 */
export interface SwitchProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  checked: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ checked, onCheckedChange, className, disabled, onClick, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(event) => {
        onCheckedChange?.(!checked);
        onClick?.(event);
      }}
      className={cn(
        "relative inline-flex h-[26px] w-11 shrink-0 items-center rounded-full transition-colors duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ink/25 disabled:opacity-50",
        checked ? "bg-ink" : "bg-surface-strong",
        className,
      )}
      {...props}
    >
      <span
        className={cn(
          // White knob, not cream — it has to read against the ink track.
          "pointer-events-none absolute top-[3px] size-5 rounded-full bg-white transition-[left] duration-150 ease-out",
          checked ? "left-[21px]" : "left-[3px]",
        )}
      />
    </button>
  ),
);
Switch.displayName = "Switch";

/** A settings row: title + description on the left, control on the right. */
export interface SettingRowProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  title: React.ReactNode;
  description?: React.ReactNode;
  control: React.ReactNode;
}

function SettingRow({
  title,
  description,
  control,
  className,
  ...props
}: SettingRowProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-6 border-b border-hairline-soft py-3.5 last:border-0",
        className,
      )}
      {...props}
    >
      <div className="min-w-0">
        <div className="text-sm font-medium text-ink">{title}</div>
        {description && (
          <div className="mt-0.5 text-xs text-muted-ink">{description}</div>
        )}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

export { Switch, SettingRow };
