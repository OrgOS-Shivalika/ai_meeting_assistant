import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Rounded-square checkbox (6px radius, 2px border) — the task tick. Checked
 * fills with success rather than ink: in this product a checked box means
 * "done", not "selected".
 */
export interface CheckboxProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  checked: boolean;
  onCheckedChange?: (checked: boolean) => void;
  size?: "sm" | "default";
  /** Draws the empty box in warning amber — used for unassigned tasks. */
  tone?: "default" | "warning";
}

const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  (
    {
      checked,
      onCheckedChange,
      size = "default",
      tone = "default",
      className,
      onClick,
      disabled,
      ...props
    },
    ref,
  ) => (
    <button
      ref={ref}
      type="button"
      role="checkbox"
      aria-checked={checked}
      disabled={disabled}
      onClick={(event) => {
        onCheckedChange?.(!checked);
        onClick?.(event);
      }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-xs border-2 transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ink/20 disabled:opacity-50",
        size === "default" ? "size-[18px]" : "size-4",
        checked
          ? "border-success bg-success text-white"
          : tone === "warning"
            ? "border-warning bg-transparent"
            : "border-hairline bg-transparent hover:border-muted-soft",
        className,
      )}
      {...props}
    >
      {checked && <Check className="size-3" strokeWidth={3} />}
    </button>
  ),
);
Checkbox.displayName = "Checkbox";

export { Checkbox };
