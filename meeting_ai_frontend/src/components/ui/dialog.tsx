import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  size?: "sm" | "default" | "lg" | "xl";
  className?: string;
}

const SIZES = {
  sm: "max-w-md",
  default: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
} as const;

function Dialog({ open, onClose, children, size = "default", className }: DialogProps) {
  React.useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0 bg-ink/35 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden
      />
      <div
        className={cn(
          "relative z-10 w-full overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-raised",
          SIZES[size],
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}

export interface DialogHeaderProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  title: React.ReactNode;
  description?: React.ReactNode;
  onClose?: () => void;
  /** Icon chip shown left of the title. */
  icon?: React.ReactNode;
}

function DialogHeader({
  title,
  description,
  onClose,
  icon,
  className,
  ...props
}: DialogHeaderProps) {
  return (
    <div
      className={cn(
        "flex items-start gap-4 border-b border-hairline-soft px-7 py-6",
        className,
      )}
      {...props}
    >
      {icon}
      <div className="min-w-0 flex-1">
        <h2 className="vb-title-lg text-[20px]">{title}</h2>
        {description && (
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted-ink">
            {description}
          </p>
        )}
      </div>
      {onClose && (
        <Button
          variant="ghost"
          size="iconSm"
          onClick={onClose}
          aria-label="Close"
          className="-mt-1 -mr-2"
        >
          <X />
        </Button>
      )}
    </div>
  );
}

function DialogBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("max-h-[70vh] overflow-y-auto px-7 py-6", className)}
      {...props}
    />
  );
}

function DialogFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2.5 border-t border-hairline-soft bg-surface-soft px-7 py-5",
        className,
      )}
      {...props}
    />
  );
}

export { Dialog, DialogHeader, DialogBody, DialogFooter };
