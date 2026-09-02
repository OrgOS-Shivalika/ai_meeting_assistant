import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Check, Copy, Mail } from "lucide-react";
import type { EmailStatus } from "../api";

/**
 * A one-time link, shown once, with whether it reached the person.
 *
 * Used at the end of both flows that mint one — inviting a member and
 * resetting a password. It used to display a generated credential; it does
 * not any more, and that is the point of the change. What is on screen now
 * lets its holder SET a password once, briefly, rather than being one.
 *
 * Three things make this a component rather than markup at each call site:
 *
 * **The delivery outcome leads.** Whether the admin still has a job to do
 * is the first thing they need, and it is the one thing they cannot work
 * out for themselves. A failed send that renders like a success leaves
 * someone locked out with nobody realising.
 *
 * **`sent` is not `delivered`.** The server reports that the mail server
 * accepted the message, which happens before any recipient is contacted —
 * so a typo'd address still reads as sent, then bounces minutes later.
 * The copy says "on its way", never "they have it", and the link stays on
 * screen as the fallback in all three states.
 *
 * **It expires.** Unlike what it replaces, this stops working — so the
 * caller states the window rather than letting an admin file it away.
 *
 * Deliberately has no backdrop-click dismissal and no Escape handler,
 * unlike every other dialog here: those reflexes are exactly what destroys
 * the only copy of the value. Leaving is an explicit click.
 */
export default function IssuedCredential({
  title,
  email,
  value,
  valueLabel = "Activation link",
  emailStatus,
  emailError,
  sentDetail,
  failedDetail,
  skippedDetail,
  footer,
  extra,
  onClose,
}: {
  title: string;
  email: string;
  value: string;
  valueLabel?: string;
  emailStatus: EmailStatus;
  emailError: string | null;
  /** One line under the green header — what the recipient now has. */
  sentDetail: ReactNode;
  failedDetail: ReactNode;
  skippedDetail: ReactNode;
  /** Closing note, e.g. the forced-password-change rule. */
  footer?: ReactNode;
  /** Anything flow-specific, rendered above the buttons. */
  extra?: ReactNode;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const doneRef = useRef<HTMLButtonElement>(null);
  const timeoutRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    doneRef.current?.focus();
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard is blocked on non-secure origins; the value is
      // select-all-able on screen as a fallback.
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="issued-credential-title"
        className="bg-white rounded-lg shadow-lg max-w-md w-full p-6"
      >
        <div className="flex items-start gap-3 mb-4">
          <div className="w-9 h-9 rounded-full bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0">
            <Check className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="min-w-0">
            <h2
              id="issued-credential-title"
              className="text-lg font-bold text-[#0F1523] leading-tight"
            >
              {title}
            </h2>
            <p className="text-xs text-[#777681] mt-0.5 truncate">{email}</p>
          </div>
        </div>

        {emailStatus === "sent" ? (
          <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-2.5 mb-4">
            <p className="text-xs font-semibold text-emerald-900 flex items-center gap-1.5">
              <Mail className="w-3.5 h-3.5" />
              On its way to {email}
            </p>
            <p className="text-[11px] text-emerald-800 mt-1 leading-relaxed">
              {sentDetail}
            </p>
          </div>
        ) : emailStatus === "failed" ? (
          <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2.5 mb-4">
            <p className="text-xs font-semibold text-red-800 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" />
              The email did not send — pass this on yourself.
            </p>
            <p className="text-[11px] text-red-700 mt-1 leading-relaxed">
              {failedDetail}
              {emailError && (
                <>
                  {" "}
                  <span className="font-mono">{emailError}</span>
                </>
              )}
            </p>
          </div>
        ) : (
          <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5 mb-4">
            <p className="text-xs font-semibold text-amber-900">
              Copy this now — it is not shown again.
            </p>
            <p className="text-[11px] text-amber-800 mt-1 leading-relaxed">
              {skippedDetail}
            </p>
          </div>
        )}

        <p className="text-[11px] font-semibold text-[#777681] uppercase tracking-wide mb-1.5">
          {valueLabel}
        </p>
        <div className="flex items-center gap-2 mb-4">
          <code className="flex-1 px-3 py-2 rounded-lg bg-slate-50 border border-slate-200 text-sm font-mono text-[#0F1523] break-all select-all">
            {value}
          </code>
          <button
            onClick={copy}
            aria-label="Copy link"
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-200 text-xs font-semibold text-slate-700 hover:bg-gray-50 transition-colors"
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-emerald-600" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>

        {extra}

        {footer && (
          <p className="text-[11px] text-[#777681] mb-5 leading-relaxed">
            {footer}
          </p>
        )}

        <button
          ref={doneRef}
          onClick={onClose}
          className="w-full px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  );
}
