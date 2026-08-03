import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { IconChip } from "./icon-chip";

/**
 * Empty states speak in the product's voice: the agents *do things*, so
 * copy leads with a verb rather than apologising for the blank screen.
 */
export interface EmptyStateProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  icon?: LucideIcon;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  /** Brand hue for the icon chip. */
  color?: string;
  /** Drops the card frame when this already sits inside one. */
  bare?: boolean;
}

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  color = "var(--vb-lavender)",
  bare,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-8 py-14 text-center",
        !bare && "rounded-lg border border-hairline bg-canvas",
        className,
      )}
      {...props}
    >
      {Icon && (
        <IconChip size="xl" color={color} strength={16} className="mb-5">
          <Icon />
        </IconChip>
      )}
      <h3 className="vb-title-md">{title}</h3>
      {description && (
        <p className="mt-2.5 max-w-[420px] text-sm leading-relaxed text-muted-ink">
          {description}
        </p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export { EmptyState };
