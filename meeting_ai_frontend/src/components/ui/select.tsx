import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Native `<select>` restyled to match Input — 44px, 12px radius, hairline.
 * Native keeps the mobile picker and needs no popover package.
 */
const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <div className="relative">
    <select
      ref={ref}
      className={cn(
        "h-11 w-full appearance-none rounded-md border border-hairline bg-canvas pr-10 pl-3.5 text-sm text-ink transition-colors outline-none focus-visible:border-ink focus-visible:ring-3 focus-visible:ring-ink/12 disabled:cursor-not-allowed disabled:bg-surface-soft disabled:opacity-60",
        className,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown className="pointer-events-none absolute top-1/2 right-3.5 size-4 -translate-y-1/2 text-muted-soft" />
  </div>
));
Select.displayName = "Select";

export { Select };
