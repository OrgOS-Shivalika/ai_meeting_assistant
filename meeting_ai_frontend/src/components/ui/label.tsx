import * as React from "react";
import { cn } from "@/lib/utils";

/** 12px medium, body-strong — sits 7px above its field. */
const Label = React.forwardRef<
  HTMLLabelElement,
  React.LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => (
  <label
    ref={ref}
    className={cn("text-xs font-medium text-body-strong", className)}
    {...props}
  />
));
Label.displayName = "Label";

/** Label + control + optional error, stacked with the system's 7px gap. */
export interface FieldProps extends React.HTMLAttributes<HTMLDivElement> {
  label?: React.ReactNode;
  htmlFor?: string;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  /** Rendered on the label's baseline, right-aligned (e.g. "Forgot?"). */
  action?: React.ReactNode;
}

function Field({
  label,
  htmlFor,
  hint,
  error,
  action,
  className,
  children,
  ...props
}: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-[7px]", className)} {...props}>
      {(label || action) && (
        <div className="flex items-center justify-between gap-3">
          {label && <Label htmlFor={htmlFor}>{label}</Label>}
          {action}
        </div>
      )}
      {children}
      {error ? (
        <p className="text-[11px] font-medium text-error">{error}</p>
      ) : (
        hint && <p className="text-[11px] text-muted-ink">{hint}</p>
      )}
    </div>
  );
}

export { Label, Field };
