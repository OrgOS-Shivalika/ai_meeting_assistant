import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Loader2, type LucideIcon } from "lucide-react";

export type ConfirmTone = "danger" | "caution";

const TONE = {
  danger: {
    iconWrap: "bg-red-50 border-red-100",
    icon: "text-red-600",
    panel: "bg-red-50 border-red-200",
    panelHeading: "text-red-800",
    panelDetail: "text-red-700",
    button: "bg-red-600 hover:bg-red-700 disabled:bg-red-300",
  },
  caution: {
    iconWrap: "bg-amber-50 border-amber-100",
    icon: "text-amber-600",
    panel: "bg-amber-50 border-amber-200",
    panelHeading: "text-amber-900",
    panelDetail: "text-amber-800",
    button: "bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300",
  },
} as const;

/**
 * Shell for a confirmation that states consequences instead of just asking
 * twice.
 *
 * Two behaviours here are deliberate and easy to lose if this gets
 * reimplemented per call site:
 *
 * **Cancel takes focus, not the confirm button.** The dialog appears under
 * a cursor already travelling toward wherever the user clicked, and Enter
 * should mean "back out".
 *
 * **A failed confirm keeps the dialog open.** `onConfirm` resolves false on
 * failure, and closing over a row that is still there reads as success.
 */
export default function ConfirmDialog({
  title,
  subtitle,
  icon: Icon = AlertTriangle,
  tone,
  warningHeading,
  warningDetail,
  consequencesLabel = "What happens",
  consequences,
  confirmLabel,
  confirmingLabel,
  failureMessage,
  closeOnSuccess = true,
  onClose,
  onConfirm,
}: {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  tone: ConfirmTone;
  warningHeading: string;
  warningDetail: string;
  consequencesLabel?: string;
  consequences: ReactNode[];
  confirmLabel: string;
  confirmingLabel: string;
  failureMessage: string;
  /**
   * Whether a successful confirm should dismiss the dialog.
   *
   * `false` for an action that produces something the user has to read
   * before leaving — a one-shot password, say. The dialog stops its busy
   * state and does nothing else; the caller is expected to swap in its own
   * result view, because closing over a value that can never be shown
   * again would lose it.
   */
  closeOnSuccess?: boolean;
  onClose: () => void;
  /** Resolves true when the action landed; false keeps the dialog open. */
  onConfirm: () => Promise<boolean>;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const t = TONE[tone];

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const run = async () => {
    setBusy(true);
    setFailed(false);
    const ok = await onConfirm();
    if (ok) {
      if (closeOnSuccess) onClose();
      else setBusy(false);
      return;
    }
    setFailed(true);
    setBusy(false);
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={() => !busy && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-warning"
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-lg shadow-lg max-w-md w-full p-6"
      >
        <div className="flex items-start gap-3 mb-4">
          <div
            className={`w-9 h-9 rounded-full border flex items-center justify-center shrink-0 ${t.iconWrap}`}
          >
            <Icon className={`w-4 h-4 ${t.icon}`} />
          </div>
          <div className="min-w-0">
            <h2
              id="confirm-dialog-title"
              className="text-lg font-bold text-[#0F1523] leading-tight"
            >
              {title}
            </h2>
            {subtitle && (
              <p className="text-xs text-[#777681] mt-0.5 truncate">{subtitle}</p>
            )}
          </div>
        </div>

        <div
          id="confirm-dialog-warning"
          className={`rounded-lg border px-3 py-2.5 mb-4 ${t.panel}`}
        >
          <p className={`text-xs font-semibold ${t.panelHeading}`}>
            {warningHeading}
          </p>
          <p className={`text-[11px] mt-1 leading-relaxed ${t.panelDetail}`}>
            {warningDetail}
          </p>
        </div>

        <p className="text-[11px] font-semibold text-[#777681] uppercase tracking-wide mb-1.5">
          {consequencesLabel}
        </p>
        <ul className="text-xs text-slate-700 space-y-1.5 mb-5">
          {consequences.map((item, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-slate-400 shrink-0">·</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>

        {failed && (
          <div className="flex items-start gap-2 p-2.5 mb-3 rounded-lg bg-amber-50 border border-amber-200">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-700" />
            <p className="text-xs text-amber-800">{failureMessage}</p>
          </div>
        )}

        <div className="flex gap-3">
          <button
            ref={cancelRef}
            onClick={onClose}
            disabled={busy}
            className="flex-1 px-4 py-2 border border-gray-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={run}
            disabled={busy}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 text-white rounded-lg text-sm font-semibold transition-colors disabled:cursor-default ${t.button}`}
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {busy ? confirmingLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
