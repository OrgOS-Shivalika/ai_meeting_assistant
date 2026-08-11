import * as React from "react";
import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex min-h-20 w-full rounded-md border border-hairline bg-canvas px-3.5 py-3 text-sm leading-relaxed text-ink transition-colors outline-none placeholder:text-muted-soft focus-visible:border-ink focus-visible:ring-3 focus-visible:ring-ink/12 disabled:cursor-not-allowed disabled:bg-surface-soft disabled:opacity-60",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export { Textarea };
