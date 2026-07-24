import {
  AlertCircle,
  CalendarDays,
  CheckCircle2,
  CircleDollarSign,
  HelpCircle,
  ListTodo,
  MessageSquareText,
  Target,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Structured, human view of a Continuum client board. The board JSON is
 * LLM-maintained (Section 5 of the prompt) so every read is defensive:
 * unknown shape → section simply doesn't render. Updates automatically
 * after each meeting because the agent rewrites the whole board.
 */

type AnyRec = Record<string, unknown>;

const asStr = (v: unknown): string | null => {
  if (typeof v === "string" && v.trim()) return v;
  if (typeof v === "number") return String(v);
  return null;
};

const asList = (v: unknown): AnyRec[] =>
  Array.isArray(v) ? (v.filter((x) => x && typeof x === "object") as AnyRec[]) : [];

const pick = (o: AnyRec, ...keys: string[]): string | null => {
  for (const k of keys) {
    const s = asStr(o[k]);
    if (s) return s;
  }
  return null;
};

const isOpen = (status: string | null): boolean => {
  if (!status) return true;
  const s = status.toLowerCase();
  return !["done", "completed", "closed", "resolved", "answered", "superseded"].some((x) =>
    s.includes(x),
  );
};

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <h3 className="mb-2.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        <Icon className="h-3.5 w-3.5" /> {title}
      </h3>
      {children}
    </div>
  );
}

const dispositionColor = (d: string | null): string => {
  const s = (d ?? "").toLowerCase();
  if (/champ|support|positive|friend/.test(s)) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (/skeptic|negative|block|hostile/.test(s)) return "bg-red-50 text-red-700 ring-red-200";
  return "bg-slate-100 text-slate-600 ring-slate-200";
};

export default function ClientOverview({ board }: { board: AnyRec | null }) {
  if (!board) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 p-4 text-xs text-slate-500">
        No meetings processed yet — the client profile, discussion summaries, and open
        items will appear here after the first meeting.
      </div>
    );
  }

  const profile = (board.client_profile ?? {}) as AnyRec;
  const discovery = (board.discovery_capture ?? {}) as AnyRec;
  const positioning = (board.our_positioning ?? {}) as AnyRec;
  const pipeline = (board.pipeline ?? {}) as AnyRec;
  const commercials = (board.commercials ?? {}) as AnyRec;

  const summaries = asList(board.meeting_summaries).slice().reverse();
  const stakeholders = asList(profile.stakeholders);
  const painPoints = asList(discovery.pain_points);
  const goals = asList(discovery.goals);
  const actionItems = asList(board.action_items).filter((t) =>
    isOpen(pick(t, "status")),
  );
  const questions = asList(board.question_tasks).filter((q) => isOpen(pick(q, "status")));
  const objections = asList(positioning.objections).filter((o) => isOpen(pick(o, "status")));
  const decisions = asList(board.decisions_log).slice(-5).reverse();

  const gate = asStr(discovery.completeness_score) ?? asStr(discovery.score);
  const budget =
    asStr(profile.budget_signals) ??
    asList(profile.budget_signals as unknown)
      .map((b) => pick(b, "signal", "note", "text"))
      .filter(Boolean)
      .join(" · ");
  const decisionProcess = asStr(profile.decision_process) ?? (
    typeof profile.decision_process === "object" && profile.decision_process
      ? pick(profile.decision_process as AnyRec, "summary", "signer", "description")
      : null
  );
  const orgNote =
    asStr(profile.org) ??
    (typeof profile.org === "object" && profile.org
      ? pick(profile.org as AnyRec, "name", "description", "industry")
      : null);
  const commercialValue = pick(commercials, "value", "status");

  return (
    <div className="space-y-3">
      {/* Snapshot strip */}
      <div className="flex flex-wrap gap-2 text-[11px]">
        {gate && (
          <span className="rounded bg-indigo-50 px-2 py-1 font-medium text-indigo-700 ring-1 ring-indigo-100">
            Discovery gate: {gate}
          </span>
        )}
        {asStr(pipeline.calls_in_stage) && (
          <span className="rounded bg-slate-100 px-2 py-1 font-medium text-slate-600 ring-1 ring-slate-200">
            {asStr(pipeline.calls_in_stage)} call(s) in stage
          </span>
        )}
        {budget && (
          <span className="rounded bg-emerald-50 px-2 py-1 font-medium text-emerald-700 ring-1 ring-emerald-100">
            💰 {budget}
          </span>
        )}
        {commercialValue && (
          <span className="rounded bg-amber-50 px-2 py-1 font-medium text-amber-700 ring-1 ring-amber-100">
            Commercials: {commercialValue}
          </span>
        )}
      </div>

      {/* About the client */}
      {(orgNote || decisionProcess || stakeholders.length > 0) && (
        <Section icon={Users} title="About the client">
          {orgNote && <p className="mb-2 text-xs text-slate-600">{orgNote}</p>}
          {decisionProcess && (
            <p className="mb-2 text-xs text-slate-600">
              <span className="font-medium text-slate-700">Decision process:</span>{" "}
              {decisionProcess}
            </p>
          )}
          {stakeholders.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {stakeholders.map((s, i) => {
                const disp = pick(s, "disposition", "stance");
                return (
                  <span
                    key={i}
                    title={pick(s, "evidence") ?? undefined}
                    className={cn(
                      "rounded px-2 py-1 text-[11px] font-medium ring-1",
                      dispositionColor(disp),
                    )}
                  >
                    {pick(s, "name", "person") ?? "?"}
                    {pick(s, "role") && (
                      <span className="opacity-70"> · {pick(s, "role")}</span>
                    )}
                    {disp && <span className="opacity-70"> · {disp}</span>}
                  </span>
                );
              })}
            </div>
          )}
        </Section>
      )}

      {/* What's been discussed — updates after every meeting */}
      {summaries.length > 0 && (
        <Section icon={MessageSquareText} title="What's been discussed">
          <ul className="space-y-2.5">
            {summaries.map((m, i) => {
              const score = pick(m, "outcome_score");
              return (
                <li key={i} className="flex gap-2.5 text-xs">
                  <div className="flex shrink-0 flex-col items-center">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-50 text-[10px] font-bold text-indigo-600">
                      {pick(m, "meeting_number") ?? summaries.length - i}
                    </span>
                    {i < summaries.length - 1 && (
                      <span className="mt-0.5 w-px flex-1 bg-slate-200" />
                    )}
                  </div>
                  <div className="pb-1">
                    <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400">
                      <CalendarDays className="h-3 w-3" />
                      {pick(m, "meeting_date", "date", "when") ?? "—"}
                      {pick(m, "stage") && <span>· {pick(m, "stage")}</span>}
                      {score && (
                        <span
                          className={cn(
                            "rounded px-1 py-0.5 font-medium",
                            score.includes("achiev")
                              ? "bg-emerald-50 text-emerald-700"
                              : score.includes("miss")
                                ? "bg-red-50 text-red-600"
                                : "bg-amber-50 text-amber-700",
                          )}
                        >
                          {score}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 leading-relaxed text-slate-700">
                      {pick(m, "summary", "text", "one_liner") ?? "—"}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {/* Pains & goals */}
      {(painPoints.length > 0 || goals.length > 0) && (
        <Section icon={Target} title="Pain points & goals">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {painPoints.length > 0 && (
              <ul className="space-y-1">
                {painPoints.map((p, i) => (
                  <li key={i} className="flex gap-1.5 text-xs text-slate-700">
                    <AlertCircle className="mt-0.5 h-3 w-3 shrink-0 text-red-400" />
                    <span>
                      {pick(p, "description", "pain", "text", "title") ?? "—"}
                      {pick(p, "cost_of_pain", "cost") && (
                        <span className="text-slate-400"> ({pick(p, "cost_of_pain", "cost")})</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {goals.length > 0 && (
              <ul className="space-y-1">
                {goals.map((g, i) => (
                  <li key={i} className="flex gap-1.5 text-xs text-slate-700">
                    <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500" />
                    <span>
                      {pick(g, "description", "goal", "text", "title") ?? "—"}
                      {pick(g, "metric") && (
                        <span className="text-slate-400"> · {pick(g, "metric")}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Section>
      )}

      {/* Open action items */}
      {actionItems.length > 0 && (
        <Section icon={ListTodo} title={`Open action items (${actionItems.length})`}>
          <ul className="space-y-1.5">
            {actionItems.map((t, i) => (
              <li key={i} className="flex items-baseline gap-2 text-xs">
                <span className="shrink-0 font-mono text-[10px] text-slate-400">
                  {pick(t, "id") ?? `T-${i + 1}`}
                </span>
                <span className="text-slate-700">{pick(t, "task", "description", "title") ?? "—"}</span>
                <span className="ml-auto shrink-0 text-[10px] text-slate-400">
                  {pick(t, "owner", "owner_name") ?? "unassigned"}
                  {pick(t, "due", "due_date") && ` · ${pick(t, "due", "due_date")}`}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Questions to ask next */}
      {questions.length > 0 && (
        <Section icon={HelpCircle} title="To ask next meeting">
          <ul className="space-y-1.5">
            {questions.map((q, i) => (
              <li key={i} className="text-xs text-slate-700">
                {(pick(q, "id") ?? "").includes("GATE") ||
                /gate/i.test(pick(q, "tags") ?? "") ? (
                  <span className="mr-1 rounded bg-indigo-50 px-1 py-0.5 text-[9px] font-bold text-indigo-600">
                    GATE
                  </span>
                ) : null}
                {pick(q, "question", "text") ?? "—"}
                {pick(q, "target") && (
                  <span className="text-slate-400"> → {pick(q, "target")}</span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Objections + recent decisions */}
      {(objections.length > 0 || decisions.length > 0) && (
        <Section icon={CircleDollarSign} title="Objections & decisions">
          {objections.length > 0 && (
            <ul className="mb-2 space-y-1">
              {objections.map((o, i) => (
                <li key={i} className="text-xs text-red-700">
                  ⚠ {pick(o, "objection", "description", "text") ?? "—"}
                  {pick(o, "handling", "best_handling") && (
                    <span className="text-slate-500"> — {pick(o, "handling", "best_handling")}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {decisions.length > 0 && (
            <ul className="space-y-1">
              {decisions.map((d, i) => (
                <li key={i} className="text-xs text-slate-700">
                  ✓ {pick(d, "decision", "description", "text") ?? "—"}
                  {pick(d, "attributed_to", "by", "who") && (
                    <span className="text-slate-400"> — {pick(d, "attributed_to", "by", "who")}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </div>
  );
}
