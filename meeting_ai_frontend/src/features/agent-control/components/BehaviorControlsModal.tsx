import { useEffect } from "react";
import { Cpu, X } from "lucide-react";
import BehaviorEditor from "./BehaviorEditor";
import type { ActiveScope } from "../types";

/**
 * A full-screen modal that hosts the BehaviorEditor for a single
 * scope (one category or one team). Opened from anywhere a user
 * encounters a category/team row — Meeting Types page, future
 * meeting detail pages, etc. — without navigating away.
 *
 * Spatially the BehaviorEditor takes the whole modal body; there is
 * no scope sidebar because the caller already picked the scope.
 *
 * Keyed remount per scope so each open is a clean fetch — avoids
 * stale data from a previously-opened scope leaking through when
 * the user opens the modal for a different category/team next.
 */
export default function BehaviorControlsModal({
  isOpen, onClose, scope,
}: {
  isOpen: boolean;
  onClose: () => void;
  scope: ActiveScope | null;
}) {
  // Escape closes the modal. Body scroll lock while open.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [isOpen, onClose]);

  if (!isOpen || !scope) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 md:p-8"
      onMouseDown={(e) => {
        // Click on the backdrop closes; clicks inside the panel
        // don't bubble because we stopPropagation on the panel.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-6xl h-full max-h-[92vh] flex flex-col overflow-hidden"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-gray-200 bg-gradient-to-r from-indigo-50 to-white">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0">
              <Cpu className="w-4 h-4 text-white" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-widest text-indigo-600">
                Agent Controls — {scope.type === "team" ? "Team" : "Category"}
              </p>
              <h2 className="text-lg font-bold text-gray-900 truncate">
                {scope.display_name}
              </h2>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg transition text-gray-500 hover:text-gray-900"
            title="Close (Esc)"
          >
            <X className="w-5 h-5" />
          </button>
        </header>

        <div className="flex-1 overflow-hidden">
          {/* Keyed remount per scope so each open starts fresh.
              Don't pass onSidebarRefresh — there's no sidebar here. */}
          <BehaviorEditor
            key={`${scope.type}-${scope.id ?? "ws"}`}
            scope={scope}
          />
        </div>
      </div>
    </div>
  );
}
