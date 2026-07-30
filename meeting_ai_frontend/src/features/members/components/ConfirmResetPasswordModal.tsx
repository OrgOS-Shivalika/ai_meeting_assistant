import { useEffect, useRef, useState } from "react";
import { Check, Copy, KeyRound } from "lucide-react";
import type { OrgMember } from "../api";
import ConfirmDialog from "./ConfirmDialog";

/**
 * Issue a new temporary password: confirm, then read the result.
 *
 * Two phases in one dialog, because the value only exists for one render.
 * The server keeps a bcrypt hash, so the response is the single moment the
 * password is legible — closing the dialog on success and leaving it to a
 * banner behind it would put the one thing the admin came for underneath
 * whatever they clicked next.
 *
 * `caution`, not `danger`: the action is disruptive but reversible — you can
 * always reset again. What earns a confirmation is the part nobody expects,
 * which is that it signs the person out everywhere immediately.
 */
export default function ConfirmResetPasswordModal({
  member,
  onClose,
  onConfirm,
}: {
  member: OrgMember;
  onClose: () => void;
  /** Resolves the new password, or null if the reset failed. */
  onConfirm: () => Promise<string | null>;
}) {
  const [issued, setIssued] = useState<string | null>(null);

  if (issued) {
    return (
      <IssuedPassword email={member.email} password={issued} onClose={onClose} />
    );
  }

  return (
    <ConfirmDialog
      tone="caution"
      icon={KeyRound}
      title="Issue a new password?"
      subtitle={`${member.name} · ${member.email}`}
      warningHeading="They will be signed out everywhere."
      warningDetail="Every device and browser they are currently signed in on stops working straight away, including sessions they did not ask to end. Their existing password stops working too."
      confirmLabel="Reset password"
      confirmingLabel="Resetting"
      failureMessage="That did not go through. Their password is unchanged — see the message above the list."
      // Stay open and hand over to `IssuedPassword` — the password cannot be
      // retrieved a second time.
      closeOnSuccess={false}
      onClose={onClose}
      onConfirm={async () => {
        const password = await onConfirm();
        if (password) setIssued(password);
        return !!password;
      }}
      consequences={[
        <>
          You get a generated password{" "}
          <strong className="font-semibold">shown once</strong>. It cannot be
          retrieved afterwards — if you miss it, run the reset again.
        </>,
        <>
          Sending it to them is your job. There is no email set up, so use a
          channel you trust.
        </>,
        <>
          They must replace it before the app will do anything else for them —
          the password you hand over works for signing in and nothing more.
        </>,
        <>
          Nothing else changes: their role, their category and team
          assignments, and their meeting history are all untouched.
        </>,
      ]}
    />
  );
}

/**
 * The password, shown once.
 *
 * No backdrop-click dismissal and no Escape handler, deliberately — every
 * other dialog in this feature has both, and here the reflex that closes
 * them destroys the only copy of the value. Leaving is an explicit click.
 */
function IssuedPassword({
  email,
  password,
  onClose,
}: {
  email: string;
  password: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const doneRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    doneRef.current?.focus();
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
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
        aria-labelledby="issued-password-title"
        className="bg-white rounded-lg shadow-lg max-w-md w-full p-6"
      >
        <div className="flex items-start gap-3 mb-4">
          <div className="w-9 h-9 rounded-full bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0">
            <Check className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="min-w-0">
            <h2
              id="issued-password-title"
              className="text-lg font-bold text-[#0F1523] leading-tight"
            >
              New password issued
            </h2>
            <p className="text-xs text-[#777681] mt-0.5 truncate">{email}</p>
          </div>
        </div>

        <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5 mb-4">
          <p className="text-xs font-semibold text-amber-900">
            Copy this now — it is not shown again.
          </p>
          <p className="text-[11px] text-amber-800 mt-1 leading-relaxed">
            Only a hash is stored, so nobody can look this up later. If it is
            lost, run the reset again to issue another.
          </p>
        </div>

        <div className="flex items-center gap-2 mb-4">
          <code className="flex-1 px-3 py-2 rounded-lg bg-slate-50 border border-slate-200 text-sm font-mono text-[#0F1523] break-all select-all">
            {password}
          </code>
          <button
            onClick={copy}
            aria-label="Copy password"
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

        <p className="text-[11px] text-[#777681] mb-5 leading-relaxed">
          Send it over a channel you trust. They will be asked to replace it the
          next time they sign in, and until they do, the API refuses everything
          except signing in and setting a password.
        </p>

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
