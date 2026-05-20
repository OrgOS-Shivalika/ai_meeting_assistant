import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * Shared shell for every dimension accordion. The dimension-specific
 * editor lives in `children`. Header shows the dimension's display
 * name + override count + a single-line inheritance summary.
 */
export default function DimensionAccordion({
  title,
  description,
  overrideCount,
  inheritanceSummary,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  description?: string;
  overrideCount: number;
  inheritanceSummary?: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-white rounded-xl border border-gray-200 mb-3 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-5 py-4 hover:bg-gray-50 transition text-left"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
            {overrideCount > 0 && (
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-rose-100 text-rose-800">
                {overrideCount} override{overrideCount === 1 ? "" : "s"}
              </span>
            )}
          </div>
          {description && (
            <p className="text-xs text-gray-500 mt-0.5">{description}</p>
          )}
          {!expanded && inheritanceSummary && (
            <p className="text-[11px] text-gray-400 mt-1 italic truncate">
              {inheritanceSummary}
            </p>
          )}
        </div>
      </button>
      {expanded && <div className="px-5 pb-5 pt-1 border-t border-gray-100">{children}</div>}
    </section>
  );
}
