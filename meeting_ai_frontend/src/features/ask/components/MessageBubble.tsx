/**
 * One chat turn rendered as user message + assistant reply.
 *
 * Assistant text is rendered with inline `[N]` citation chips that
 * open popovers + deep-link to the source. While the turn is still
 * streaming we show progress badges (planning -> retrieving -> streaming
 * -> validating). Final state shows the per-stage timing summary.
 */
import { AlertTriangle, Loader2, Sparkles } from "lucide-react";
import { Fragment, useMemo } from "react";
import CitationChip from "./CitationChip";
import type { ChatTurn, CitationDTO, TurnStatus } from "../types";
import { Badge } from "@/components/ui/badge";
import { IconChip } from "@/components/ui/icon-chip";

interface Props {
  turn: ChatTurn;
}

const STATUS_LABEL: Record<TurnStatus, string> = {
  pending: "Submitting",
  planning: "Planning query",
  retrieving: "Pulling context",
  streaming: "Answering",
  validating: "Verifying citations",
  completed: "Done",
  no_context: "No matching context",
  failed: "Failed",
};

// Split a string like "Alice leads Helios [1] and Phoenix [2]." into a
// list of text / chip alternating tokens, so we can render React
// children with citation chips at the right place.
function tokenizeAnswer(
  text: string,
  citations: CitationDTO[],
): Array<string | { chip: CitationDTO }> {
  if (!citations.length) return [text];
  const byIndex = new Map(citations.map((c) => [c.index, c]));
  const re = /\[(\d+)\]/g;
  const out: Array<string | { chip: CitationDTO }> = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const cit = byIndex.get(Number(m[1]));
    if (cit) {
      out.push({ chip: cit });
    } else {
      // Unknown index — the backend already strips these in `done`'s
      // answer_text, but during streaming we may render an in-flight
      // [N] before validation runs. Keep the literal text in that
      // case so the answer reads naturally.
      out.push(m[0]);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function StatusBadge({ status, error }: { status: TurnStatus; error: string | null }) {
  if (status === "completed") return null;
  const failed = status === "failed";
  const noCtx = status === "no_context";
  const inFlight = !failed && !noCtx;

  return (
    <Badge
      variant={failed ? "error" : noCtx ? "secondary" : "warning"}
      title={error || undefined}
    >
      {inFlight && <Loader2 className="size-3 animate-spin" />}
      {failed && <AlertTriangle className="size-3" />}
      {STATUS_LABEL[status]}
    </Badge>
  );
}

function RetrievalSummary({ turn }: { turn: ChatTurn }) {
  const r = turn.retrieval_summary;
  const p = turn.plan_summary;
  if (!r && !p) return null;
  const parts: string[] = [];
  if (r) {
    parts.push(`${r.chunks} chunk${r.chunks === 1 ? "" : "s"}`);
    if (r.entities) parts.push(`${r.entities} entit${r.entities === 1 ? "y" : "ies"}`);
    if (r.relationships)
      parts.push(`${r.relationships} relationship${r.relationships === 1 ? "" : "s"}`);
    if (r.effective_scope_type) parts.push(`scope: ${r.effective_scope_type}`);
  } else if (p) {
    parts.push(`planned: ${p.query_type}`);
    if (p.detected_entity_names.length)
      parts.push(`entities: ${p.detected_entity_names.join(", ")}`);
  }
  if (!parts.length) return null;
  return (
    <p className="font-mono text-[10px] text-muted-soft">{parts.join(" · ")}</p>
  );
}

export default function MessageBubble({ turn }: Props) {
  const tokens = useMemo(
    () => tokenizeAnswer(turn.answer_text, turn.citations),
    [turn.answer_text, turn.citations],
  );

  return (
    <div className="space-y-5">
      {/* User message — ink bubble, tail on the bottom-right. */}
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-[18px] rounded-br-[4px] bg-ink px-[18px] py-3.5 text-on-ink">
          <p className="text-sm leading-relaxed whitespace-pre-wrap">
            {turn.query_text}
          </p>
        </div>
      </div>

      {/* Assistant reply — cream bubble, tail on the top-left. */}
      <div className="flex items-start gap-3">
        <IconChip
          size="sm"
          color="var(--vb-lavender)"
          strength={22}
          className="rounded-[10px]"
        >
          <Sparkles />
        </IconChip>
        <div className="min-w-0 flex-1">
          {(turn.status !== "completed" || turn.retrieval_summary) && (
            <div className="mb-2 flex items-center gap-2">
              <StatusBadge status={turn.status} error={turn.error} />
              <RetrievalSummary turn={turn} />
            </div>
          )}
          <div className="rounded-[18px] rounded-tl-[4px] bg-surface-card px-5 py-[18px]">
            {turn.answer_text ? (
              <p className="text-sm leading-relaxed break-words whitespace-pre-wrap text-body-strong">
                {tokens.map((t, i) =>
                  typeof t === "string" ? (
                    <Fragment key={i}>{t}</Fragment>
                  ) : (
                    <CitationChip
                      key={i}
                      citation={t.chip}
                      runId={turn.run_id}
                    />
                  ),
                )}
                {turn.status === "streaming" && (
                  <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-pink align-text-bottom" />
                )}
              </p>
            ) : (
              <p className="text-sm text-muted-soft">
                {turn.status === "failed"
                  ? turn.error ?? "Something went wrong."
                  : "Thinking…"}
              </p>
            )}
            {turn.status === "failed" && turn.error && turn.answer_text && (
              <p className="mt-2 text-xs text-error">{turn.error}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
