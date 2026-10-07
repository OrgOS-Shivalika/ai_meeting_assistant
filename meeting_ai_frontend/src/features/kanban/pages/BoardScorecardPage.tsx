// Per-member progress on one board — its own tab beside Board and Summary.
//
// Built on the project's own primitives rather than hand-rolled markup:
// `Table` for the list (its header/row/cell rules ARE the house style),
// `Progress` for both bars, `Segmented` for the sort control, `Badge` for the
// counts that need emphasis, `Card`, `EmptyState`, `Skeleton`, `Avatar`,
// `IconChip`. An earlier version reimplemented every one of those with raw
// divs and drifted from the rest of the app — different paddings, different
// type sizes, different hover.
//
// Design notes, because several are load-bearing:
//
//   * THE BAR IS THE SCORE. Length is the score out of 100, colour is its
//     band (green >= 70, amber >= 40, red below). It used to draw workload
//     scaled to the busiest member, which meant two people with different
//     scores could render identical bars — three members here hold the same
//     three cards, so their workload bars matched exactly while their scores
//     differed. A bar beside a number should BE that number.
//   * Every row carries a left accent: error when something is overdue,
//     warning when something shipped late. Eleven overdue cards and none used
//     to look identical until you read the digits.
//   * The activity breakdown is collapsed behind a disclosure row. It was four
//     grey clauses under every row and it buried the numbers that matter.
//
// A LIST, deliberately. An earlier version led with tiles and two donuts; they
// summarised the board rather than the people, which is what the Summary tab
// is already for.
//
// Fetched rather than derived from the board payload the layout already holds,
// because half of it cannot be: the activity counts come from `task_activity`,
// which the board endpoint does not carry and should not start carrying for
// every card on every load.
//
// Visible to anyone who can open the board. `get_viewable_board` on the server
// is the whole gate, and it 404s for a board outside the caller's reach, so
// this page cannot be used to probe which boards exist.
import { useEffect, useMemo, useState } from "react";
import { ChevronRight, HelpCircle, Inbox, Users } from "lucide-react";
import { useBoardOutletContext } from "./BoardLayout";
import { fetchBoardScorecard } from "../api";
import type { MemberScore } from "../api";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { IconChip } from "@/components/ui/icon-chip";
import { Progress } from "@/components/ui/progress";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

/** Score bands and the activity hue, straight off the design tokens. */
const HUE = {
  good: "var(--vb-success)",
  fair: "var(--vb-warning)",
  poor: "var(--vb-error)",
  activity: "var(--vb-lavender)",
};

const SCORE_HELP =
  "100 × done/held  −  30 × overdue/held  −  15 × late/held.\n\n" +
  "Overdue (still open, past due) costs twice what late (finished, but after " +
  "the due date) costs — an overdue card is work still being waited on, a " +
  "late one is work that arrived. The two are mutually exclusive per card, " +
  "so the penalties never stack past 30 points.\n\n" +
  "A dash means they hold no cards — not the same as scoring zero.";

type SortKey = "score" | "held" | "activity";

const SORTS = [
  { value: "score" as const, label: "Score" },
  { value: "held" as const, label: "Workload" },
  { value: "activity" as const, label: "Activity" },
];

export default function BoardScorecardPage() {
  const { board } = useBoardOutletContext();
  const [rows, setRows] = useState<MemberScore[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortKey>("score");
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setRows(null);
    setError(null);
    fetchBoardScorecard(board.id)
      .then((d) => alive && setRows(d.members))
      .catch((e) => alive && setError(e?.message || "Failed to load progress"));
    return () => {
      alive = false;
    };
  }, [board.id]);

  // Only the activity bar is still relative — it compares people to the
  // busiest person, excluding the Unassigned pile, which is routinely an
  // order of magnitude larger and would squash every human row to a sliver.
  const maxActivity = useMemo(
    () =>
      Math.max(
        1,
        ...(rows || [])
          .filter((r) => !r.is_unassigned)
          .map((r) => r.activity.total),
      ),
    [rows],
  );

  const totals = useMemo(() => {
    const m = rows || [];
    return {
      people: m.filter((r) => !r.is_unassigned).length,
      held: m.reduce((s, x) => s + x.assigned, 0),
      done: m.reduce((s, x) => s + x.completed, 0),
      late: m.reduce((s, x) => s + x.late, 0),
      overdue: m.reduce((s, x) => s + x.overdue, 0),
    };
  }, [rows]);

  const sorted = useMemo(() => {
    if (!rows) return null;
    const people = rows.filter((r) => !r.is_unassigned);
    const orphan = rows.filter((r) => r.is_unassigned);
    const by: Record<SortKey, (r: MemberScore) => number> = {
      // Unscored people sort BELOW scored ones rather than above them, which
      // a bare `?? 0` would do.
      score: (r) => (r.score === null ? -1 : r.score),
      held: (r) => r.assigned,
      activity: (r) => r.activity.total,
    };
    // The orphan row is a footnote about the board, not a competitor in a
    // ranking of people — it stays pinned last under every sort.
    return [...people]
      .sort((a, b) => by[sortBy](b) - by[sortBy](a))
      .concat(orphan);
  }, [rows, sortBy]);

  return (
    <div className="vb-no-scrollbar overflow-y-auto px-9 pt-6 pb-18">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="vb-title-sm">Member progress</h2>
          {rows !== null && rows.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <Badge variant="secondary" size="sm">
                {totals.people} members
              </Badge>
              <Badge variant="outline" size="sm">
                {totals.held} held
              </Badge>
              <Badge variant="success" size="sm" dot>
                {totals.done} done
              </Badge>
              {totals.late > 0 && (
                <Badge variant="warning" size="sm" dot>
                  {totals.late} late
                </Badge>
              )}
              {totals.overdue > 0 && (
                <Badge variant="error" size="sm" dot>
                  {totals.overdue} overdue
                </Badge>
              )}
            </div>
          ) : (
            <p className="mt-1 text-[11px] text-muted-soft">
              Each bar is that person's score out of 100.
            </p>
          )}
        </div>

        {rows !== null && rows.length > 1 && (
          <Segmented
            size="sm"
            options={SORTS}
            value={sortBy}
            onChange={setSortBy}
          />
        )}
      </div>

      {error && (
        <Card padding="sm">
          <p className="text-[13px] text-error">{error}</p>
        </Card>
      )}

      {!error && rows === null && <LoadingRows />}

      {!error && rows !== null && rows.length === 0 && (
        <Card padding="none">
          <EmptyState
            bare
            icon={Users}
            title="No progress to show yet"
            description="Assign a card to somebody, or move one on the board, and they'll appear here."
          />
        </Card>
      )}

      {!error && sorted !== null && sorted.length > 0 && (
        <Card padding="none" className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-10 pr-0">#</TableHead>
                <TableHead>Member</TableHead>
                <TableHead className="w-[86px] text-right">Done</TableHead>
                <TableHead className="hidden w-[64px] text-right sm:table-cell">
                  Open
                </TableHead>
                <TableHead
                  className="hidden w-[64px] text-right sm:table-cell"
                  title="Finished, but after the due date"
                >
                  Late
                </TableHead>
                <TableHead
                  className="hidden w-[76px] text-right sm:table-cell"
                  title="Still open and past the due date"
                >
                  Overdue
                </TableHead>
                <TableHead className="hidden w-[74px] text-right lg:table-cell">
                  Cycle
                </TableHead>
                <TableHead
                  className="w-[104px] cursor-help text-right"
                  title={SCORE_HELP}
                >
                  <span className="inline-flex items-center gap-1">
                    Score
                    <HelpCircle className="size-3" />
                  </span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((m, i) => (
                <MemberRows
                  key={m.user_id}
                  m={m}
                  rank={m.is_unassigned ? null : i + 1}
                  maxActivity={maxActivity}
                  open={openId === m.user_id}
                  onToggle={() =>
                    setOpenId(openId === m.user_id ? null : m.user_id)
                  }
                />
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function MemberRows({
  m,
  rank,
  maxActivity,
  open,
  onToggle,
}: {
  m: MemberScore;
  /** null for the Unassigned row — it is not ranked against people. */
  rank: number | null;
  maxActivity: number;
  open: boolean;
  onToggle: () => void;
}) {
  // `open` from the API INCLUDES overdue. Carve it out for the Open column so
  // a late card is not counted in both.
  const stillOpen = Math.max(0, m.open - m.overdue);
  const hasDetail = m.activity.total > 0;

  return (
    <>
      <TableRow
        onClick={() => hasDetail && onToggle()}
        className={cn(
          "border-l-2 border-l-transparent",
          hasDetail && "cursor-pointer",
          // The fastest way to spot a row that needs attention.
          m.overdue > 0 && "border-l-error",
          m.overdue === 0 && m.late > 0 && "border-l-warning",
          m.is_unassigned && "border-t border-hairline bg-surface-soft/60",
          open && "bg-surface-soft",
        )}
      >
        <TableCell className="pr-0 font-mono text-[11px] text-muted-soft">
          {rank ?? ""}
        </TableCell>

        <TableCell>
          <div className="flex items-center gap-3">
            {m.is_unassigned ? (
              <IconChip size="sm" color="var(--vb-muted-soft)">
                <Inbox />
              </IconChip>
            ) : (
              <Avatar size="sm" name={m.name} />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span
                  className={cn(
                    "truncate font-medium",
                    m.is_unassigned ? "text-muted-ink italic" : "text-ink",
                  )}
                >
                  {m.name}
                </span>
                {m.is_unassigned && (
                  <span className="text-[10px] text-muted-soft">
                    nobody holds these
                  </span>
                )}
                {m.assigned_by_label > 0 && (
                  <Badge
                    variant="secondary"
                    size="sm"
                    title={
                      `${m.assigned_by_label} of these cards are credited from ` +
                      `the meeting's text label, not a real assignment`
                    }
                  >
                    {m.assigned_by_label} by label
                  </Badge>
                )}
                {hasDetail && (
                  <ChevronRight
                    className={cn(
                      "size-3 shrink-0 text-muted-soft transition-transform",
                      open && "rotate-90",
                    )}
                  />
                )}
              </div>

              {m.score !== null ? (
                <Progress
                  size="sm"
                  className="mt-2 max-w-sm"
                  value={m.score}
                  color={scoreHue(m.score)}
                  title={
                    `Score ${m.score} of 100 — ${m.completed} of ${m.assigned} done` +
                    (m.late > 0 ? `, ${m.late} late` : "") +
                    (m.overdue > 0 ? `, ${m.overdue} overdue` : "")
                  }
                />
              ) : (
                <p className="mt-1 text-[11px] text-muted-soft">
                  {m.is_unassigned
                    ? "Nobody holds these — not scored"
                    : "No cards held — activity only"}
                </p>
              )}
            </div>
          </div>
        </TableCell>

        <TableCell className="text-right font-mono text-[13px] text-muted-ink tabular-nums">
          {m.completed || <Dash />}
          {m.completion_rate !== null && (
            <span className="ml-1 text-[10px] text-muted-soft">
              {m.completion_rate}%
            </span>
          )}
        </TableCell>
        <TableCell className="hidden text-right font-mono text-[13px] text-muted-ink tabular-nums sm:table-cell">
          {stillOpen || <Dash />}
        </TableCell>
        <TableCell className="hidden text-right sm:table-cell">
          {m.late > 0 ? (
            <Badge variant="warning" size="sm" title={`${m.late} finished after the due date`}>
              {m.late}
            </Badge>
          ) : (
            <Dash />
          )}
        </TableCell>
        <TableCell className="hidden text-right sm:table-cell">
          {m.overdue > 0 ? (
            <Badge variant="error" size="sm" title={`${m.overdue} still open and past due`}>
              {m.overdue}
            </Badge>
          ) : (
            <Dash />
          )}
        </TableCell>
        <TableCell className="hidden text-right font-mono text-[13px] text-muted-ink tabular-nums lg:table-cell">
          {m.avg_cycle_days === null ? (
            <Dash />
          ) : (
            <span
              title={
                m.cycle_approx === 0
                  ? `Measured from the completion timestamp on all ` +
                    `${m.cycle_exact} finished cards`
                  : `${m.cycle_exact} of ${m.cycle_exact + m.cycle_approx} ` +
                    `finished cards have a real completion timestamp; the rest ` +
                    `fall back to the card's last edit, which can overstate it`
              }
            >
              {/* A tilde whenever part of the average is estimated. Showing an
                  estimate as a bare number is how the old proxy went unnoticed. */}
              {m.cycle_approx > 0 && "~"}
              {m.avg_cycle_days}d
            </span>
          )}
        </TableCell>

        <TableCell className="text-right">
          <span
            className={cn(
              "block font-mono text-[17px] leading-none font-semibold tabular-nums",
              m.score === null ? "text-muted-soft" : scoreTint(m.score),
            )}
            title={
              m.score === null
                ? m.is_unassigned
                  ? "Nobody holds these cards, so there is nobody to score"
                  : "Holds no cards on this board — nothing to score"
                : `${m.completed} of ${m.assigned} done` +
                  (m.late > 0 ? `, ${m.late} of them late` : "") +
                  (m.overdue > 0 ? `, ${m.overdue} overdue` : "")
            }
          >
            {m.score === null ? "—" : m.score}
          </span>
        </TableCell>
      </TableRow>

      {/* Activity detail — collapsed by default. It used to be four grey
          clauses under every row, which buried the numbers that matter. */}
      {open && hasDetail && (
        <TableRow className="hover:bg-transparent">
          <TableCell />
          <TableCell colSpan={7} className="pt-0">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 pb-1 pl-[46px]">
              <Stat label="created" value={m.activity.created} />
              <Stat label="moved" value={m.activity.moved} />
              <Stat label="status changes" value={m.activity.status_changes} />
              <Stat label="comments" value={m.activity.comments} />
              {m.activity.assignments_made > 0 && (
                <Stat label="assignments" value={m.activity.assignments_made} />
              )}
              <span className="flex items-center gap-2">
                <Progress
                  size="sm"
                  className="h-1 w-16"
                  value={(m.activity.total / maxActivity) * 100}
                  color={HUE.activity}
                />
                <span className="font-mono text-[10px] text-muted-soft">
                  {m.activity.total} total
                </span>
              </span>
              {m.last_active && (
                <span
                  className="font-mono text-[10px] text-muted-soft"
                  title={new Date(m.last_active).toLocaleString()}
                >
                  active {ago(m.last_active)}
                </span>
              )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="font-mono text-[13px] font-medium text-muted-ink tabular-nums">
        {value}
      </span>
      <span className="text-[10px] text-muted-soft">{label}</span>
    </span>
  );
}

function LoadingRows() {
  return (
    <Card padding="none" className="overflow-hidden">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="flex items-center gap-3 border-b border-hairline-soft px-[22px] py-3.5 last:border-0"
        >
          <Skeleton className="size-7 rounded-[8px]" />
          <div className="flex-1">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="mt-2 h-1.5 w-full max-w-sm rounded-full" />
          </div>
          <Skeleton className="h-6 w-16" />
        </div>
      ))}
    </Card>
  );
}

/** A zero that reads as "none", not as a number worth comparing. */
function Dash() {
  return <span className="text-muted-soft opacity-50">—</span>;
}

/** Relative age. Scans faster than a date in a list you read top to bottom. */
function ago(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function scoreTint(score: number): string {
  if (score >= 70) return "text-success";
  if (score >= 40) return "text-warning";
  return "text-error";
}

function scoreHue(score: number): string {
  if (score >= 70) return HUE.good;
  if (score >= 40) return HUE.fair;
  return HUE.poor;
}
