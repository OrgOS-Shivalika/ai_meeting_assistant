import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Pill badges. Status variants use a 12% wash of their hue over white and
 * can carry a leading dot — the system's standard "live state" treatment.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full font-semibold whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "bg-ink text-on-ink",
        secondary: "bg-surface-card text-muted-ink",
        outline: "border border-hairline bg-canvas text-body",
        success: "bg-success/12 text-success",
        warning: "bg-warning/14 text-warning",
        error: "bg-error/10 text-error",
        info: "bg-info/12 text-info",
        pink: "bg-pink/12 text-pink",
        lavender: "bg-lavender/22 text-purple-700",
        onDark: "bg-white/12 text-on-ink",
      },
      size: {
        default: "px-[9px] py-1 text-[11px]",
        sm: "px-2 py-0.5 text-[10px]",
        lg: "px-[11px] py-[5px] text-xs",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  /** Renders the 5–6px status dot in the badge's own colour. */
  dot?: boolean;
}

function Badge({ className, variant, size, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, size }), className)} {...props}>
      {dot && (
        <span className="size-1.5 shrink-0 rounded-full bg-current" aria-hidden />
      )}
      {children}
    </span>
  );
}

export { Badge, badgeVariants };
