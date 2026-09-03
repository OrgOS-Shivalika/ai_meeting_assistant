/** Arrow geometry for the workflow canvas. Pure, so it can be checked without
 *  a DOM — see `workflowGeometry.check.ts`. */

export const NODE_W = 132;
export const NODE_H = 56; // two lines: the column name and what is in it
export const GAP = 40;
export const ARC = 46; // how far an arc bulges from the straight line

export type XY = { x: number; y: number };

/**
 * Where a ray from `c` towards `t` crosses `c`'s box.
 *
 * Nodes are rectangles, so this scales the direction by whichever axis hits
 * the edge first. Without it every arrowhead lands at a node's CENTRE, hidden
 * underneath the box it is pointing at.
 */
export function border(c: XY, t: XY, pad = 8): XY {
  const dx = t.x - c.x;
  const dy = t.y - c.y;
  const s = Math.max(
    Math.abs(dx) / (NODE_W / 2 + pad),
    Math.abs(dy) / (NODE_H / 2 + pad),
  );
  return s > 0 ? { x: c.x + dx / s, y: c.y + dy / s } : c;
}

/**
 * The curve between two node centres: endpoints on the two borders, and a
 * control point pushed out along the edge's own NORMAL.
 *
 * The normal rather than a fixed "up" is what generalises the old layout: for
 * a left-to-right edge it points up and for a right-to-left one down, which is
 * the forward-above / backward-below rule that keeps a workflow with
 * backtracking from turning into spaghetti — and it survives a node being
 * dragged somewhere a straight row no longer explains.
 */
export function arc(a: XY, b: XY) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const ctrl = {
    x: (a.x + b.x) / 2 + (dy / len) * ARC,
    y: (a.y + b.y) / 2 - (dx / len) * ARC,
  };
  const p1 = border(a, ctrl);
  const p2 = border(b, ctrl);
  return {
    ctrl,
    d: `M ${p1.x} ${p1.y} Q ${ctrl.x} ${ctrl.y} ${p2.x} ${p2.y}`,
    // Midpoint of the quadratic — where the validator badge sits.
    mid: {
      x: (p1.x + 2 * ctrl.x + p2.x) / 4,
      y: (p1.y + 2 * ctrl.y + p2.y) / 4,
    },
  };
}
