import { useRef, useState } from "react";
import type { WorkflowTransition } from "../api";
import type { ColumnWithTasks } from "../types";
import { ARC, GAP, NODE_H, NODE_W, arc, type XY } from "./workflowGeometry";

/**
 * The workflow as a diagram — statuses as boxes, transitions as arrows.
 *
 * Hand-drawn SVG rather than a graph library, deliberately: a dependency for
 * this would be several hundred KB to lay out at most a dozen nodes.
 *
 * Layout is FREE — every node can be dragged anywhere and its position is
 * remembered. The default is the old left-to-right row, so a board nobody has
 * rearranged looks exactly as it did.
 *
 * Two things that keep it readable:
 *
 * - **Arrows bulge perpendicular to their own direction.** For the default row
 *   that means forward arcs above and backward arcs below, which is what stops
 *   a workflow with any backtracking (every real one) turning into spaghetti.
 *   Generalising it to the perpendicular is what makes it survive a node being
 *   dragged off the row.
 * - **A wildcard ("from anywhere") is a BADGE on the target, not N arrows.**
 *   Rendering it literally is what makes Jira's own diagrams unreadable.
 */

export default function WorkflowDiagram({
  boardId,
  columns,
  rules,
  onSelectRule,
  onSelectColumn,
  selectedColumnId,
}: {
  /** Only used to key the saved layout — positions are per board. */
  boardId: number;
  columns: ColumnWithTasks[];
  rules: WorkflowTransition[];
  /** Clicking an arrow hands back its index so the caller can open that rule
   *  in the Text view. This is what makes the diagram a way IN to editing
   *  rather than a picture beside it — without needing a graph editor. */
  onSelectRule?: (index: number) => void;
  /** Clicking a status box. The caller opens a sidebar for it. */
  onSelectColumn?: (columnId: number) => void;
  /** Drawn with a ring so the sidebar and the canvas agree on what is open. */
  selectedColumnId?: number | null;
}) {
  // Panning. A workflow of any size runs off the edge, and a canvas you can
  // only reach with a horizontal scrollbar is unusable once arrows arc above
  // and below the row too.
  //
  // Held in state and applied to an inner <g> rather than scrolling the
  // container: scroll would clip the arcs, and transforming the group keeps
  // the whole graph — including the parts currently off-screen — as one
  // coordinate space that hit-testing still works in.
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  // ponytail: node positions live in localStorage, not the database. They are
  // cosmetic and per-person — nothing downstream reads them — so a column and
  // an API endpoint would be storage plus a migration bought for a preference
  // that costs nothing if another browser forgets it. Move it server-side when
  // a team needs to agree on one layout.
  const layoutKey = `wf-layout:${boardId}`;
  const [pos, setPos] = useState<Record<number, XY>>(() => {
    try {
      return JSON.parse(localStorage.getItem(layoutKey) || "{}");
    } catch {
      return {};
    }
  });
  const persist = (next: Record<number, XY>) => {
    try {
      localStorage.setItem(layoutKey, JSON.stringify(next));
    } catch {
      // Private mode, quota. A forgotten layout is not worth an error.
    }
  };

  const onPointerDown = (e: React.PointerEvent) => {
    // Left button only, and never when the gesture started on a node or an
    // arrow — those are controls, and starting a pan on them would make them
    // impossible to click reliably.
    if (e.button !== 0) return;
    if ((e.target as Element).closest("[data-wf-hit]")) return;
    drag.current = { x: e.clientX, y: e.clientY, ox: pan.x, oy: pan.y };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };
  // Cursor-anchored zoom: the point under the pointer stays put. Zooming to
  // the canvas ORIGIN instead is the thing that makes a canvas feel broken —
  // you aim at a node, scroll, and it slides away from you.
  const onWheel = (e: React.WheelEvent) => {
    const rect = (e.currentTarget as Element).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    setZoom((z) => {
      const next = Math.min(2.5, Math.max(0.35, z * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
      setPan((p) => ({
        x: px - ((px - p.x) * next) / z,
        y: py - ((py - p.y) * next) / z,
      }));
      return next;
    });
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    setPan({
      x: drag.current.ox + (e.clientX - drag.current.x),
      y: drag.current.oy + (e.clientY - drag.current.y),
    });
  };
  const endDrag = () => {
    drag.current = null;
  };

  const index = new Map(columns.map((c, i) => [c.id, i]));
  const midY = ARC + 12;
  /** Top-left of a node: its saved spot, else its slot in the default row. */
  const at = (id: number): XY => {
    const i = index.get(id) ?? 0;
    return pos[id] ?? { x: i * (NODE_W + GAP), y: midY - NODE_H / 2 };
  };
  const center = (id: number): XY => {
    const p = at(id);
    return { x: p.x + NODE_W / 2, y: p.y + NODE_H / 2 };
  };
  // Dragging a node. Kept separate from the pan drag: this one has to divide
  // by zoom (the pointer moves in screen pixels, the node lives in canvas
  // units) and has to know whether it travelled at all, because a press that
  // never moved is a click that should open the sidebar.
  const node = useRef<
    { id: number; x: number; y: number; ox: number; oy: number; moved: boolean } | null
  >(null);

  const onNodeDown = (e: React.PointerEvent, id: number) => {
    if (e.button !== 0) return;
    const p = at(id);
    node.current = { id, x: e.clientX, y: e.clientY, ox: p.x, oy: p.y, moved: false };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };
  const onNodeMove = (e: React.PointerEvent) => {
    const d = node.current;
    if (!d) return;
    const dx = (e.clientX - d.x) / zoom;
    const dy = (e.clientY - d.y) / zoom;
    // 3px of slop: a mouse always moves a little between press and release,
    // and without it every click would register as a drag and the sidebar
    // would never open.
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (d.moved) setPos((p) => ({ ...p, [d.id]: { x: d.ox + dx, y: d.oy + dy } }));
  };
  const onNodeUp = () => {
    const d = node.current;
    node.current = null;
    if (!d) return;
    if (d.moved) persist(pos);
    else onSelectColumn?.(d.id);
  };

  // Only ALLOW rows are arrows. A block is a property of a column, not a
  // path between two, and drawing it as an arrow would show a route that
  // exists precisely to be impossible.
  const allow = rules.filter((r) => (r.kind || "allow") === "allow");
  const directed = allow.filter((r) => r.from_column_id !== null);
  const wildcardTargets = new Set(
    allow.filter((r) => r.from_column_id === null).map((r) => r.to_column_id),
  );
  const noEntry = new Set(
    rules.filter((r) => r.kind === "block_entry").map((r) => r.to_column_id),
  );
  const noExit = new Set(
    rules.filter((r) => r.kind === "block_exit").map((r) => r.to_column_id),
  );

  // Short text badges rather than lucide icons: an icon component renders a
  // NESTED <svg> inside this canvas, where Tailwind's CSS sizing fights the
  // element's own width/height attributes and positioning gets fragile. A
  // glyph in a <text> is laid out by the same coordinate system as everything
  // else here, and `<title>` still carries the full wording for a reader.
  const nameOf = (id: number | null) =>
    id === null ? "Anywhere" : columns.find((c) => c.id === id)?.name || "—";

  const validators = (r: WorkflowTransition) =>
    [
      r.admins_only && { glyph: "A", label: "Admins only" },
      r.require_assignee && { glyph: "@", label: "Needs an assignee" },
      r.require_due_date && { glyph: "D", label: "Needs a due date" },
    ].filter(Boolean) as { glyph: string; label: string }[];

  if (!columns.length) return null;

  const moved = pan.x !== 0 || pan.y !== 0 || zoom !== 1 || Object.keys(pos).length > 0;

  return (
    <div className="absolute inset-0 overflow-hidden">
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1">
        <button
          onClick={() => setZoom((z) => Math.max(0.35, z / 1.2))}
          aria-label="Zoom out"
          className="size-6 rounded-md border border-hairline bg-canvas text-[13px] leading-none text-muted-ink hover:text-ink"
        >
          −
        </button>
        <span className="w-10 text-center font-mono text-[10px] text-muted-soft tabular-nums">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom((z) => Math.min(2.5, z * 1.2))}
          aria-label="Zoom in"
          className="size-6 rounded-md border border-hairline bg-canvas text-[13px] leading-none text-muted-ink hover:text-ink"
        >
          +
        </button>
        {moved && (
          <button
            onClick={() => {
              setPan({ x: 0, y: 0 });
              setZoom(1);
              // Also throws away a hand-made layout, which is the point: it is
              // the way back when the boxes end up in a mess.
              setPos({});
              persist({});
            }}
            className="ml-1 rounded-md border border-hairline bg-canvas px-2 py-1 text-[10px] font-medium text-muted-ink hover:text-ink"
          >
            Reset
          </button>
        )}
      </div>
      <svg
        width="100%"
        height="100%"
        role="img"
        aria-label="Workflow diagram"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onWheel={onWheel}
        className={`h-full w-full touch-none select-none ${
          drag.current ? "cursor-grabbing" : "cursor-grab"
        }`}
      >
      {/* Dot grid. Without a textured ground a pan reads as "the boxes
          jumped" rather than "the canvas moved" — there is nothing else on
          screen to show that anything travelled. Anchored to the pan so it
          scrolls WITH the content. */}
      <defs>
        <pattern
          id="wf-dots"
          width={24 * zoom}
          height={24 * zoom}
          patternUnits="userSpaceOnUse"
          x={pan.x}
          y={pan.y}
        >
          <circle cx="1" cy="1" r="1" className="fill-muted-soft" opacity="0.35" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#wf-dots)" />
      <g transform={`translate(${pan.x + 24}, ${pan.y + 24}) scale(${zoom})`}>
        <defs>
          <marker
            id="wf-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
          </marker>
        </defs>

        {directed.map((r) => {
          // Index into the FULL rules array, not into `directed` — the caller
          // edits `rules`, and a wildcard filtered out above would otherwise
          // shift every subsequent index by one and open the wrong rule.
          const i = rules.indexOf(r);
          const fromId = r.from_column_id as number;
          if (!index.has(fromId) || !index.has(r.to_column_id)) return null;
          const { d, mid } = arc(center(fromId), center(r.to_column_id));
          const marks = validators(r);
          return (
            <g
              key={`d-${i}`}
              className={
                onSelectRule
                  ? "cursor-pointer text-muted-soft hover:text-ink"
                  : "text-muted-soft"
              }
              data-wf-hit="edge"
              onClick={onSelectRule ? () => onSelectRule(i) : undefined}
            >
              <title>
                {nameOf(r.from_column_id)} → {nameOf(r.to_column_id)}
                {onSelectRule ? " — click to edit" : ""}
              </title>
              {/* A transparent fat stroke over the same path: a 1.5px line is
                  almost impossible to hit with a mouse, and an arrow you
                  cannot click is not a control. */}
              {onSelectRule && (
                <path d={d} fill="none" stroke="transparent" strokeWidth="14" />
              )}
              <path
                d={d}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                markerEnd="url(#wf-arrow)"
                opacity="0.75"
              />
              {marks.length > 0 && (
                <g transform={`translate(${mid.x - (marks.length * 14 + 4) / 2}, ${mid.y - 8})`}>
                  <rect
                    width={marks.length * 14 + 4}
                    height="16"
                    rx="8"
                    className="fill-canvas"
                    stroke="currentColor"
                    strokeWidth="1"
                    opacity="0.95"
                  />
                  {marks.map(({ glyph, label }, j) => (
                    <text
                      key={label}
                      x={j * 14 + 9}
                      y={8}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      className="fill-ink"
                      style={{ fontSize: 9, fontWeight: 700 }}
                    >
                      <title>{label}</title>
                      {glyph}
                    </text>
                  ))}
                </g>
              )}
            </g>
          );
        })}

        {columns.map((c) => {
          const p = at(c.id);
          return (
          <g
            key={c.id}
            data-wf-hit="node"
            transform={`translate(${p.x}, ${p.y})`}
            onPointerDown={(e) => onNodeDown(e, c.id)}
            onPointerMove={onNodeMove}
            onPointerUp={onNodeUp}
            onPointerCancel={onNodeUp}
            className="cursor-grab text-muted-soft active:cursor-grabbing"
          >
            <title>
              {c.name} — drag to move{onSelectColumn ? ", click for details" : ""}
            </title>
            <rect
              width={NODE_W}
              height={NODE_H}
              rx="8"
              className={
                selectedColumnId === c.id ? "fill-surface-strong" : "fill-surface-soft"
              }
              stroke="currentColor"
              strokeWidth={selectedColumnId === c.id ? 2 : 1}
              opacity="0.95"
            />
            {/* The board's REAL columns, with what is actually in them.
                A workflow drawn over abstract boxes makes you hold the mapping
                in your head; showing the live card count means the diagram is
                about this board rather than a diagram of a board. */}
            <text
              x={NODE_W / 2}
              y={NODE_H / 2 - 6}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-ink"
              style={{ fontSize: 12, fontWeight: 600 }}
            >
              {c.name.length > 16 ? `${c.name.slice(0, 15)}…` : c.name}
            </text>
            <text
              x={NODE_W / 2}
              y={NODE_H / 2 + 10}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-muted-ink"
              style={{ fontSize: 9.5 }}
            >
              {c.tasks.length} card{c.tasks.length === 1 ? "" : "s"}
              {c.wip_limit != null ? ` · limit ${c.wip_limit}` : ""}
              {c.is_done_column ? " · done" : ""}
            </text>
            {(noEntry.has(c.id) || noExit.has(c.id)) && (
              <>
                <title>
                  {noEntry.has(c.id) && noExit.has(c.id)
                    ? "Sealed — nothing in, nothing out"
                    : noEntry.has(c.id)
                      ? "Closed — nothing can be moved in"
                      : "Locked — cards cannot be moved out"}
                </title>
                <rect
                  x={-6}
                  y={-8}
                  width="52"
                  height="16"
                  rx="8"
                  className="fill-canvas"
                  stroke="currentColor"
                  strokeWidth="1"
                />
                <text
                  x={20}
                  y={1}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  className="fill-error"
                  style={{ fontSize: 8, fontWeight: 700, letterSpacing: 0.3 }}
                >
                  {noEntry.has(c.id) && noExit.has(c.id)
                    ? "SEALED"
                    : noEntry.has(c.id)
                      ? "NO ENTRY"
                      : "NO EXIT"}
                </text>
              </>
            )}
            {wildcardTargets.has(c.id) && (
              <>
                <title>Reachable from anywhere</title>
                <rect
                  x={NODE_W - 34}
                  y={-8}
                  width="36"
                  height="16"
                  rx="8"
                  className="fill-canvas"
                  stroke="currentColor"
                  strokeWidth="1"
                />
                <text
                  x={NODE_W - 16}
                  y={1}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  className="fill-muted-ink"
                  style={{ fontSize: 8, fontWeight: 700, letterSpacing: 0.3 }}
                >
                  ANY
                </text>
              </>
            )}
          </g>
          );
        })}
      </g>
      </svg>
      <p className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 text-[10px] text-muted-soft">
        Drag a status to move it · drag the background to pan · scroll to zoom ·
        click a status for details, an arrow to edit it
      </p>
    </div>
  );
}
