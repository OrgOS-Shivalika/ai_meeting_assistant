import * as React from "react";
import { ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Every full-page screen opens the same way: a pink uppercase eyebrow, a
 * display headline with negative tracking, a muted one-liner, and actions
 * pinned to the baseline on the right.
 */
export interface PageHeaderProps
  extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
  /** Tiny uppercase label — usually the sidebar section this screen lives in. */
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** `sm` (34px) for sub-pages, `md` (40px) for section landings. */
  size?: "sm" | "md";
}

function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  size = "md",
  className,
  children,
  ...props
}: PageHeaderProps) {
  return (
    <header
      className={cn(
        "mb-7 flex flex-wrap items-end justify-between gap-6",
        className,
      )}
      {...props}
    >
      <div className="min-w-0">
        {eyebrow && <p className="vb-eyebrow mb-2.5">{eyebrow}</p>}
        <h1 className={size === "md" ? "vb-display-md" : "vb-display-sm"}>
          {title}
        </h1>
        {description && (
          <p className="mt-2.5 max-w-[560px] text-[15px] text-muted-ink">
            {description}
          </p>
        )}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
    </header>
  );
}

function PageContainer({
  className,
  width = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  width?: "narrow" | "default" | "wide" | "full";
}) {
  return (
    <div
      className={cn(
        "mx-auto px-11 pt-11 pb-18",
        width === "narrow" && "max-w-[920px]",
        width === "default" && "max-w-[1100px]",
        width === "wide" && "max-w-[1180px]",
        width === "full" && "max-w-none",
        className,
      )}
      {...props}
    />
  );
}

/**
 * The "‹ All boards" link above a detail-page header. Renders whatever
 * element the caller passes as `as` (usually react-router's `Link`).
 */
export interface BackLinkProps extends React.HTMLAttributes<HTMLElement> {
  as?: React.ElementType;
  /** react-router `Link` target. */
  to?: string;
  /** Plain-anchor target, when `as` is left as the default `a`. */
  href?: string;
  children: React.ReactNode;
}

function BackLink({ as, className, children, ...props }: BackLinkProps) {
  const Comp = as ?? "a";
  return (
    <Comp
      className={cn(
        "mb-3.5 inline-flex items-center gap-1.5 text-[13px] font-medium text-muted-ink transition-colors hover:text-ink",
        className,
      )}
      {...props}
    >
      <ChevronLeft className="size-[15px]" />
      {children}
    </Comp>
  );
}

export { PageHeader, PageContainer, BackLink };
