import { Sparkles } from "lucide-react";
import type { MemoryLifecycleStatus } from "../types";

interface AIMemoryStatusDotProps {
  embeddingStatus?: MemoryLifecycleStatus;
  graphStatus?: MemoryLifecycleStatus;
  size?: "xs" | "sm";
  showLabel?: boolean;
  /**
   * The sparkle is sitting on a solid-coloured pill rather than a pale tint.
   * Its own hue is then unreliable — "ready" green on a green Completed pill
   * is invisible — so it renders white and leans on the `quiet` opacity split
   * instead: faint = nothing to do, bright = processing (pulsing) or failed.
   */
  onFill?: boolean;
}

type CombinedState =
  | "ready"
  | "processing"
  | "pending"
  | "skipped"
  | "failed"
  | "absent";

const TERMINAL_GOOD: Record<"embedding" | "graph", MemoryLifecycleStatus[]> = {
  embedding: ["embedded", "skipped"],
  graph: ["extracted", "skipped"],
};

const isTerminalGood = (
  stage: "embedding" | "graph",
  s?: MemoryLifecycleStatus,
): boolean => !!s && TERMINAL_GOOD[stage].includes(s);

const combine = (
  e?: MemoryLifecycleStatus,
  g?: MemoryLifecycleStatus,
): CombinedState => {
  if (!e && !g) return "absent";
  if (e === "failed" || g === "failed") return "failed";
  if (e === "processing" || g === "processing") return "processing";
  if (e === "pending" || g === "pending") return "pending";
  if (isTerminalGood("embedding", e) && isTerminalGood("graph", g))
    return "ready";
  if (e === "skipped" && g === "skipped") return "skipped";
  return "pending";
};

// Rendered as a sparkle rather than a dot on purpose. This sits beside the
// meeting's status pill, which carries its own coloured dot — two identical
// dots side by side read as one repeated signal, when in fact they track
// different things (processing status vs. AI memory lifecycle). The glyph
// keeps them tellable apart at a glance.
//
// `quiet` marks the states worth de-emphasising: ready and skipped need no
// attention, so they recede instead of competing with the status pill.
const STYLE: Record<
  CombinedState,
  { color: string; animate: string; label: string; quiet?: boolean }
> = {
  ready:      { color: "var(--vb-success)",    animate: "", label: "AI memory ready", quiet: true },
  processing: { color: "var(--vb-warning)",    animate: "animate-pulse", label: "AI memory processing" },
  pending:    { color: "var(--vb-muted-soft)", animate: "", label: "AI memory pending", quiet: true },
  skipped:    { color: "var(--vb-muted-soft)", animate: "", label: "AI memory skipped", quiet: true },
  failed:     { color: "var(--vb-error)",      animate: "", label: "AI memory failed" },
  absent:     { color: "var(--vb-muted-soft)", animate: "", label: "AI memory unknown", quiet: true },
};

export default function AIMemoryStatusDot({
  embeddingStatus,
  graphStatus,
  size = "xs",
  showLabel = false,
  onFill = false,
}: AIMemoryStatusDotProps) {
  const state = combine(embeddingStatus, graphStatus);
  if (state === "absent" && !showLabel) return null;
  const style = STYLE[state];
  // Sized to sit on the text baseline inside a status pill rather than
  // tower over it — 10px matches the pill's own type size.
  const dim = size === "xs" ? "w-2.5 h-2.5" : "w-3.5 h-3.5";
  const tip = [
    style.label,
    `Embeddings: ${embeddingStatus ?? "unknown"}`,
    `Graph: ${graphStatus ?? "unknown"}`,
  ].join(" · ");

  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={tip}
      aria-label={style.label}
    >
      <Sparkles
        className={`${dim} shrink-0 ${style.animate}`}
        style={{
          color: onFill ? "#fff" : style.color,
          opacity: style.quiet ? 0.55 : 1,
        }}
      />
      {showLabel && (
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          {state}
        </span>
      )}
    </span>
  );
}
