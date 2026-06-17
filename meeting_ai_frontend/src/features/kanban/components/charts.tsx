// Phase 14 — small SVG chart primitives used by the Summary view.
//
// Pure presentational components. No external chart library — keeps
// the bundle lean and gives us complete control over styling so the
// charts match the rest of the dashboard's design system.
//
// Three chart types:
//   - DonutChart        ring of pie segments, legend on the right
//   - StackedBarChart   one horizontal bar with proportional segments
//   - TrendChart        sparkline-style area + line for time-series data
//
// All charts skip rendering when there's no data so the parent doesn't
// need to feature-detect.

// ---------------------------------------------------------------------------
// Shared types + tint table. Tint keys must stay in sync with the
// other dashboard primitives — we use the same palette across tiles,
// breakdown bars, and these charts.
// ---------------------------------------------------------------------------

export interface ChartSegment {
  label: string;
  value: number;
  tint: string; // matches keys in TINT below
}

const TINT: Record<string, string> = {
  slate: "#94a3b8",
  indigo: "#6366f1",
  amber: "#f59e0b",
  emerald: "#10b981",
  rose: "#f43f5e",
  cyan: "#06b6d4",
  violet: "#8b5cf6",
  pink: "#ec4899",
};
const TINT_BG: Record<string, string> = {
  slate: "bg-slate-400",
  indigo: "bg-indigo-500",
  amber: "bg-amber-500",
  emerald: "bg-emerald-500",
  rose: "bg-rose-500",
  cyan: "bg-cyan-500",
  violet: "bg-violet-500",
  pink: "bg-pink-500",
};

const fillFor = (tint: string) => TINT[tint] || TINT.slate;
const bgFor = (tint: string) => TINT_BG[tint] || TINT_BG.slate;

// ---------------------------------------------------------------------------
// DonutChart — proportional segments rendered as SVG arcs around a
// center hole. Used for status + priority breakdowns.
// ---------------------------------------------------------------------------

interface DonutProps {
  segments: ChartSegment[];
  size?: number;       // outer diameter in px
  thickness?: number;  // ring thickness in px
  centerLabel?: string;
  centerValue?: string | number;
}

export function DonutChart({
  segments,
  size = 160,
  thickness = 22,
  centerLabel,
  centerValue,
}: DonutProps) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total === 0) {
    return (
      <p className="text-[11px] italic text-slate-400 text-center py-6">
        No data.
      </p>
    );
  }

  const cx = size / 2;
  const cy = size / 2;
  const r = (size - thickness) / 2;
  // Render the donut as concentric stroke-dasharray segments around a
  // base circle — each segment knows how much of the circumference it
  // owns and where it starts. Avoids the trig of explicit arc paths
  // and stays perfectly precise.
  const circumference = 2 * Math.PI * r;

  let acc = 0;
  return (
    <div className="flex items-center gap-4">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="shrink-0"
        role="img"
        aria-label="donut chart"
      >
        {/* Track */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="#f1f5f9"
          strokeWidth={thickness}
        />
        {segments.map((seg) => {
          const fraction = seg.value / total;
          const dash = fraction * circumference;
          const gap = circumference - dash;
          // Rotate so segments start at the top (12 o'clock) and run
          // clockwise — matches reading conventions.
          const offset = -acc;
          acc += dash;
          return (
            <circle
              key={seg.label}
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={fillFor(seg.tint)}
              strokeWidth={thickness}
              strokeDasharray={`${dash} ${gap}`}
              strokeDashoffset={offset}
              transform={`rotate(-90 ${cx} ${cy})`}
            />
          );
        })}
        {/* Center label */}
        {(centerLabel || centerValue != null) && (
          <g>
            {centerValue != null && (
              <text
                x={cx}
                y={cy - 2}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize="22"
                fontWeight="900"
                fill="#0f172a"
              >
                {centerValue}
              </text>
            )}
            {centerLabel && (
              <text
                x={cx}
                y={cy + 16}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize="9"
                fontWeight="700"
                fill="#64748b"
                letterSpacing="1"
              >
                {centerLabel.toUpperCase()}
              </text>
            )}
          </g>
        )}
      </svg>

      {/* Legend */}
      <ul className="flex-1 min-w-0 space-y-1 text-[11px]">
        {segments.map((seg) => {
          const pct = Math.round((seg.value / total) * 100);
          return (
            <li key={seg.label} className="flex items-center gap-2">
              <span
                className={`w-2.5 h-2.5 rounded-sm shrink-0 ${bgFor(seg.tint)}`}
              />
              <span className="flex-1 min-w-0 truncate text-slate-700">
                {seg.label}
              </span>
              <span className="font-bold text-slate-700 shrink-0">
                {seg.value}
              </span>
              <span className="text-slate-400 shrink-0 w-9 text-right">
                {pct}%
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StackedBarChart — single horizontal bar split into proportional
// segments. Compact "100% stacked" view; great for status overview
// where you want one-line visibility into "what's left".
// ---------------------------------------------------------------------------

export function StackedBarChart({ segments }: { segments: ChartSegment[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total === 0) {
    return (
      <p className="text-[11px] italic text-slate-400 text-center py-3">
        No data.
      </p>
    );
  }
  return (
    <div className="space-y-1.5">
      <div className="w-full h-3 rounded-full bg-slate-100 overflow-hidden flex">
        {segments
          .filter((s) => s.value > 0)
          .map((seg) => {
            const pct = (seg.value / total) * 100;
            return (
              <div
                key={seg.label}
                className={`h-full ${bgFor(seg.tint)}`}
                style={{ width: `${pct}%` }}
                title={`${seg.label}: ${seg.value}`}
              />
            );
          })}
      </div>
      <ul className="flex items-center flex-wrap gap-x-3 gap-y-0.5 text-[10px]">
        {segments
          .filter((s) => s.value > 0)
          .map((seg) => (
            <li key={seg.label} className="flex items-center gap-1">
              <span
                className={`w-1.5 h-1.5 rounded-sm ${bgFor(seg.tint)}`}
              />
              <span className="text-slate-600">{seg.label}</span>
              <span className="font-bold text-slate-700">{seg.value}</span>
            </li>
          ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TrendChart — area + line over time. Used to plot tasks created and
// completed per day for the last 14 days. Each series has its own
// color; the area sits behind the line for shading.
// ---------------------------------------------------------------------------

export interface TrendSeries {
  label: string;
  tint: string;
  points: number[]; // length must equal labels.length
}

export function TrendChart({
  labels,
  series,
  height = 80,
}: {
  labels: string[];
  series: TrendSeries[];
  height?: number;
}) {
  const n = labels.length;
  if (n === 0 || series.length === 0) {
    return (
      <p className="text-[11px] italic text-slate-400 text-center py-3">
        No data.
      </p>
    );
  }
  // Find the global max so series share a y-scale.
  const allValues = series.flatMap((s) => s.points);
  const max = Math.max(1, ...allValues);
  const padX = 6;
  const padY = 6;
  const w = 320; // viewBox width; SVG scales to container
  const usableW = w - padX * 2;
  const usableH = height - padY * 2;
  const stepX = n > 1 ? usableW / (n - 1) : 0;

  const pointXY = (idx: number, value: number) => {
    const x = padX + idx * stepX;
    const y = padY + usableH - (value / max) * usableH;
    return [x, y] as const;
  };

  return (
    <div>
      <svg
        viewBox={`0 0 ${w} ${height}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
        role="img"
        aria-label="trend chart"
      >
        {/* Subtle horizontal gridlines at 0 / 50% / 100% of max */}
        {[0, 0.5, 1].map((f) => {
          const y = padY + usableH * (1 - f);
          return (
            <line
              key={f}
              x1={padX}
              x2={w - padX}
              y1={y}
              y2={y}
              stroke="#e2e8f0"
              strokeWidth={0.5}
              strokeDasharray={f === 0 ? undefined : "2 2"}
            />
          );
        })}

        {series.map((s) => {
          const fill = fillFor(s.tint);
          const points = s.points
            .map((v, i) => {
              const [x, y] = pointXY(i, v);
              return `${x.toFixed(2)},${y.toFixed(2)}`;
            })
            .join(" ");
          // Build the area path: line points + close to baseline.
          const areaPath = (() => {
            const segs = s.points.map((v, i) => {
              const [x, y] = pointXY(i, v);
              return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
            });
            const [lastX] = pointXY(n - 1, 0);
            const [firstX] = pointXY(0, 0);
            const baseY = padY + usableH;
            segs.push(`L ${lastX.toFixed(2)} ${baseY}`);
            segs.push(`L ${firstX.toFixed(2)} ${baseY}`);
            segs.push("Z");
            return segs.join(" ");
          })();
          return (
            <g key={s.label}>
              <path d={areaPath} fill={fill} opacity={0.12} />
              <polyline
                points={points}
                fill="none"
                stroke={fill}
                strokeWidth={1.5}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {/* Endpoint dots so single-value series remain visible */}
              {s.points.map((v, i) => {
                const [x, y] = pointXY(i, v);
                return (
                  <circle
                    key={i}
                    cx={x}
                    cy={y}
                    r={1.5}
                    fill={fill}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* X-axis labels — show first / middle / last to avoid clutter. */}
      <div className="flex items-center justify-between mt-1 text-[9px] text-slate-400">
        <span>{labels[0]}</span>
        {n > 2 && <span>{labels[Math.floor(n / 2)]}</span>}
        <span>{labels[n - 1]}</span>
      </div>

      {/* Legend */}
      <ul className="flex items-center gap-3 mt-1 text-[10px]">
        {series.map((s) => (
          <li key={s.label} className="flex items-center gap-1">
            <span className={`w-2 h-2 rounded-sm ${bgFor(s.tint)}`} />
            <span className="text-slate-600">{s.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
