import * as React from "react";
import { cn } from "@/lib/utils";

/** Loading placeholder on the cream ramp — never a cool-gray shimmer. */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-surface-card", className)}
      {...props}
    />
  );
}

export { Skeleton };
