// Shared skeleton primitive — single source of truth for shimmer
// placeholders across the app. Keeps every page using the same
// background tone and pulse animation so loading states don't look
// like five different components glued together.
//
// Usage:
//   <Skeleton className="h-4 w-32" />                  // any shape
//   <SkeletonText lines={3} />                         // n stacked lines
//   <SkeletonCard className="h-32" />                  // rounded card placeholder
//   <SkeletonAvatar size={32} />                       // circle
//   <SkeletonStack>{...skeletons}</SkeletonStack>      // pre-pulsed group
//
// All variants render `animate-pulse` + `bg-slate-200` (tailwind only,
// no new dep). To disable the pulse — e.g. inside an already-pulsing
// container — pass `noPulse`.

import type { ReactNode } from "react";

type BaseProps = {
  className?: string;
  noPulse?: boolean;
};

export function Skeleton({ className = "", noPulse = false }: BaseProps) {
  return (
    <div
      className={`${noPulse ? "" : "animate-pulse"} bg-slate-200 rounded ${className}`}
      aria-hidden
    />
  );
}

// Stacked text lines. Last line is shorter so it reads as "paragraph"
// rather than "block" — visual cue the eye expects from real prose.
export function SkeletonText({
  lines = 3,
  className = "",
  noPulse = false,
}: BaseProps & { lines?: number }) {
  return (
    <div className={`space-y-2 ${noPulse ? "" : "animate-pulse"} ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={`h-3 bg-slate-200 rounded ${i === lines - 1 ? "w-3/5" : "w-full"}`}
        />
      ))}
    </div>
  );
}

// Card-shaped placeholder — matches the rounded-2xl + border style
// used by most content cards in the app. Default height covers the
// common "small card" footprint; override via className.
export function SkeletonCard({ className = "" }: BaseProps) {
  return (
    <div
      className={`animate-pulse bg-slate-100 rounded-2xl border border-slate-200 ${className || "h-32"}`}
      aria-hidden
    />
  );
}

export function SkeletonAvatar({ size = 32, className = "" }: BaseProps & { size?: number }) {
  return (
    <div
      className={`animate-pulse bg-slate-200 rounded-full ${className}`}
      style={{ width: size, height: size }}
      aria-hidden
    />
  );
}

// Wrapper that pulses all children as one unit — cheaper than every
// child carrying its own animate-pulse, and animations stay in sync.
export function SkeletonStack({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`animate-pulse ${className}`}>{children}</div>;
}

// Pill-shaped placeholder for status chips / badges.
export function SkeletonPill({ className = "" }: BaseProps) {
  return (
    <div
      className={`animate-pulse bg-slate-200 rounded-full ${className || "h-4 w-16"}`}
      aria-hidden
    />
  );
}
