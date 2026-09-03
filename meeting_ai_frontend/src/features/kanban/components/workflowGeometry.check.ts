/**
 * Self-check for the workflow arrow geometry.  Run: `node <this file>`
 * (Node 22+ strips the types itself; nothing to install.)
 *
 * Nothing imports this, so it is not bundled. It exists because the arc math
 * is the one part of the canvas that fails SILENTLY: a wrong normal or a bad
 * border clip still renders a picture, just a wrong one, and nobody notices
 * until arrows point at nothing.
 */
import { ARC, NODE_H, NODE_W, arc, border } from "./workflowGeometry.ts";

let failed = 0;
const check = (label: string, ok: boolean, detail?: unknown) => {
  if (!ok) failed++;
  console.log(`${ok ? "ok  " : "FAIL"}  ${label}`, ok ? "" : detail ?? "");
};
const near = (a: number, b: number, eps = 0.001) => Math.abs(a - b) < eps;

const c = { x: 0, y: 0 };

// --- border: the endpoint must land ON the box, never at the centre --------
const right = border(c, { x: 1000, y: 0 });
check("clips to the right edge", near(right.x, NODE_W / 2 + 8) && near(right.y, 0), right);

const up = border(c, { x: 0, y: -1000 });
check("clips to the top edge", near(up.x, 0) && near(up.y, -(NODE_H / 2 + 8)), up);

// A target INSIDE the box still projects out to the border rather than
// collapsing to the centre — otherwise two overlapping nodes draw a zero
// length path and the arrowhead vanishes.
const inside = border(c, { x: 5, y: 2 });
check(
  "a target inside the box still lands on the border",
  near(Math.max(Math.abs(inside.x) / (NODE_W / 2 + 8), Math.abs(inside.y) / (NODE_H / 2 + 8)), 1),
  inside,
);

check("a zero-length direction does not divide by zero", (() => {
  const p = border(c, c);
  return Number.isFinite(p.x) && Number.isFinite(p.y);
})());

// --- arc: the bulge direction is what keeps the graph readable -------------
const fwd = arc({ x: 0, y: 100 }, { x: 400, y: 100 });
check("a forward edge bulges ABOVE the row", fwd.ctrl.y < 100, fwd.ctrl);
check("  by exactly ARC", near(fwd.ctrl.y, 100 - ARC), fwd.ctrl);

const back = arc({ x: 400, y: 100 }, { x: 0, y: 100 });
check("a backward edge bulges BELOW the row", back.ctrl.y > 100, back.ctrl);

// Dragged off the row: the same rule has to still separate the two directions,
// which a hardcoded "up" would not.
const a2 = { x: 0, y: 0 };
const b2 = { x: 300, y: 300 };
const diagFwd = arc(a2, b2);
const diagBack = arc(b2, a2);
check(
  "the two directions bulge to OPPOSITE sides when off the row",
  Math.sign(diagFwd.ctrl.x - 150) !== Math.sign(diagBack.ctrl.x - 150) &&
    Math.sign(diagFwd.ctrl.y - 150) !== Math.sign(diagBack.ctrl.y - 150),
  [diagFwd.ctrl, diagBack.ctrl],
);
check(
  "the control point sits ARC away from the midpoint",
  near(Math.hypot(diagFwd.ctrl.x - 150, diagFwd.ctrl.y - 150), ARC),
  diagFwd.ctrl,
);

// The path has to be a real quadratic, not NaN — a single NaN silently blanks
// the whole <path> with no error anywhere.
check("the path string is finite", !/NaN|Infinity/.test(diagFwd.d), diagFwd.d);
check(
  "the badge sits between the endpoints",
  diagFwd.mid.x > 0 && diagFwd.mid.x < 300,
  diagFwd.mid,
);

// Thrown rather than `process.exit`: this file is inside `src`, so `tsc -b`
// typechecks it, and node's globals are not in the app's type environment.
// An uncaught throw exits non-zero all the same.
if (failed) throw new Error(`${failed} geometry check(s) FAILED`);
console.log("\nall geometry checks passed");
