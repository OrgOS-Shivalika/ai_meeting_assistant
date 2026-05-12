/**
 * Tiny indicator that summarizes a meeting's AI-memory readiness in a
 * single dot. Used on MeetingCard and MeetingRow.
 *
 * State table (precedence: failed > processing > pending > skipped > ready):
 *   ready        — both embedding and graph are terminal-good
 *   processing   — at least one stage is mid-flight
 *   pending      — at least one stage hasn't started yet
 *   skipped      — terminal-but-nothing-to-do (e.g. empty transcript)
 *   failed       — at least one stage failed
 *   absent       — fields not present on the meeting payload (older API)
 */
import type { MemoryLifecycleStatus } from "../types";

interface AIMemoryStatusDotProps {
  embeddingStatus?: MemoryLifecycleStatus;
  graphStatus?: MemoryLifecycleStatus;
  size?: "xs" | "sm";
  showLabel?: boolean;
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
  // Both must be terminal-good (embedded/extracted or skipped) to be ready.
  if (isTerminalGood("embedding", e) && isTerminalGood("graph", g))
    return "ready";
  if (e === "skipped" && g === "skipped") return "skipped";
  return "pending";
};

const STYLE: Record<
  CombinedState,
  { dotClass: string; ring: string; label: string }
> = {
  ready:      { dotClass: "bg-emerald-500", ring: "shadow-[0_0_6px_rgba(16,185,129,0.5)]", label: "AI memory ready" },
  processing: { dotClass: "bg-amber-500",  ring: "shadow-[0_0_6px_rgba(245,158,11,0.5)] animate-pulse", label: "AI memory processing" },
  pending:    { dotClass: "bg-slate-300",  ring: "", label: "AI memory pending" },
  skipped:    { dotClass: "bg-slate-300",  ring: "", label: "AI memory skipped" },
  failed:     { dotClass: "bg-rose-500",   ring: "shadow-[0_0_6px_rgba(244,63,94,0.5)]", label: "AI memory failed" },
  absent:     { dotClass: "bg-slate-200",  ring: "", label: "AI memory unknown" },
};

export default function AIMemoryStatusDot({
  embeddingStatus,
  graphStatus,
  size = "xs",
  showLabel = false,
}: AIMemoryStatusDotProps) {
  const state = combine(embeddingStatus, graphStatus);
  if (state === "absent" && !showLabel) return null;
  const style = STYLE[state];
  const dim = size === "xs" ? "w-1.5 h-1.5" : "w-2 h-2";

  // Detailed tooltip — shown on hover. Cheaper than a popover and the
  // information needs zero interaction to consume.
  const tip = [
    `Embeddings: ${embeddingStatus ?? "unknown"}`,
    `Graph: ${graphStatus ?? "unknown"}`,
  ].join(" · ");

  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={tip}
      aria-label={style.label}
    >
      <span className={`${dim} rounded-full ${style.dotClass} ${style.ring}`} />
      {showLabel && (
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
          {state}
        </span>
      )}
    </span>
  );
}
