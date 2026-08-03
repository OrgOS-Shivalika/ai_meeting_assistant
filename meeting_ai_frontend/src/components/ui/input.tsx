import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * 44px tall, 12px radius, hairline border on canvas. Focus thickens the
 * border to ink and adds a soft 3px ring — the system's only focus motif.
 */
const inputClass =
  "flex h-11 w-full rounded-md border border-hairline bg-canvas px-3.5 text-sm text-ink transition-colors outline-none placeholder:text-muted-soft focus-visible:border-ink focus-visible:ring-3 focus-visible:ring-ink/12 disabled:cursor-not-allowed disabled:bg-surface-soft disabled:opacity-60 file:border-0 file:bg-transparent file:text-sm file:font-medium";

const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, type, ...props }, ref) => (
  <input ref={ref} type={type} className={cn(inputClass, className)} {...props} />
));
Input.displayName = "Input";

export interface SearchInputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Defaults to Lucide's Search. */
  icon?: LucideIcon;
  wrapperClassName?: string;
}

/** Input with a leading glyph — the search field used on every list screen. */
const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(
  ({ className, wrapperClassName, icon: Icon, ...props }, ref) => (
    <div className={cn("relative", wrapperClassName)}>
      {Icon && (
        <Icon className="pointer-events-none absolute top-1/2 left-3.5 size-[15px] -translate-y-1/2 text-muted-soft" />
      )}
      <input
        ref={ref}
        type="search"
        className={cn(inputClass, Icon && "pl-[38px]", className)}
        {...props}
      />
    </div>
  ),
);
SearchInput.displayName = "SearchInput";

export { Input, SearchInput, inputClass };
