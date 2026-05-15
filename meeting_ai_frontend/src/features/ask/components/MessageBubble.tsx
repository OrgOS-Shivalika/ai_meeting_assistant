/**
 * One chat turn rendered as user message + assistant reply.
 *
 * Assistant text is rendered with inline `[N]` citation chips that
 * open popovers + deep-link to the source. While the turn is still
 * streaming we show progress badges (planning -> retrieving -> streaming
 * -> validating). Final state shows the per-stage timing summary.
 */
import { AlertTriangle, Loader2, Sparkles, User } from "lucide-react";
import { Fragment, useMemo } from "react";
import CitationChip from "./CitationChip";
import type { ChatTurn, CitationDTO, TurnStatus } from "../types";

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
    <div
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${
        failed
          ? "bg-red-50 text-red-700 border-red-200"
          : noCtx
          ? "bg-slate-50 text-slate-600 border-slate-200"
          : "bg-amber-50 text-amber-700 border-amber-200"
      }`}
      title={error || undefined}
    >
      {inFlight && <Loader2 className="w-3 h-3 animate-spin" />}
      {failed && <AlertTriangle className="w-3 h-3" />}
      {STATUS_LABEL[status]}
    </div>
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
    <p className="text-[10px] text-slate-400 font-medium tracking-wide">
      {parts.join(" · ")}
    </p>
  );
}

export default function MessageBubble({ turn }: Props) {
  const tokens = useMemo(
    () => tokenizeAnswer(turn.answer_text, turn.citations),
    [turn.answer_text, turn.citations],
  );

  return (
    <div className="space-y-3">
      {/* User message */}
      <div className="flex items-start gap-3 justify-end">
        <div className="max-w-[80%] bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5">
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{turn.query_text}</p>
        </div>
        <div className="w-7 h-7 bg-slate-200 rounded-full flex items-center justify-center shrink-0">
          <User className="w-3.5 h-3.5 text-slate-600" />
        </div>
      </div>

      {/* Assistant reply */}
      <div className="flex items-start gap-3">
        <div className="w-7 h-7 bg-gradient-to-br from-indigo-500 to-purple-500 rounded-full flex items-center justify-center shrink-0">
          <Sparkles className="w-3.5 h-3.5 text-white" />
        </div>
        <div className="max-w-[80%] flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <StatusBadge status={turn.status} error={turn.error} />
            <RetrievalSummary turn={turn} />
          </div>
          <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
            {turn.answer_text ? (
              <p className="text-sm leading-relaxed text-slate-800 whitespace-pre-wrap break-words">
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
                  <span className="inline-block w-1.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom" />
                )}
              </p>
            ) : (
              <p className="text-sm text-slate-400 italic">
                {turn.status === "failed"
                  ? turn.error ?? "Something went wrong."
                  : "Thinking…"}
              </p>
            )}
            {turn.status === "failed" && turn.error && turn.answer_text && (
              <p className="mt-2 text-xs text-red-600">{turn.error}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
