import { useEffect, useState } from "react";
import { AlertCircle, Check, Loader2, ShieldCheck, ShieldOff, X } from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import { usePermissions } from "../../auth/hooks/usePermissions";
import type { Participant } from "../types";

/**
 * Who attended this meeting, and which of them can actually open it.
 *
 * The distinction is the entire reason this exists. Attendance is what
 * makes someone a member of a meeting, but the pipeline can only make a
 * TRUSTED link from an exact calendar hit — a fuzzy name-token match is
 * recorded as `heuristic` and grants nothing, and every attendance row
 * predating the access-control migration is `legacy`, which also grants
 * nothing. Both are common, and neither corrects itself.
 *
 * So a row can show a name, an email and an avatar and still mean "this
 * person cannot read this meeting". That is invisible without a screen
 * like this, and unfixable without the confirm action on it.
 */
export default function AttendeeAccessModal({
  meetingId,
  participants,
  onClose,
  onChanged,
}: {
  meetingId: number;
  participants: Participant[];
  onClose: () => void;
  /** Called with the updated row so the page can refresh its copy. */
  onChanged: (updated: Participant) => void;
}) {
  const { canManage } = usePermissions();
  const [rows, setRows] = useState<Participant[]>(participants);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && busyId === null) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busyId, onClose]);

  const setLink = async (row: Participant, userId: string | null) => {
    setBusyId(row.id);
    setError(null);
    try {
      const updated: Participant = await apiClient(
        `/meetings/${meetingId}/participants/${row.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: userId }),
        },
      );
      setRows((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      onChanged(updated);
    } catch (e: any) {
      setError(e?.message || "That change could not be applied.");
    } finally {
      setBusyId(null);
    }
  };

  const withAccess = rows.filter((r) => r.grants_access).length;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={() => busyId === null && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="attendee-access-title"
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-lg shadow-lg max-w-lg w-full p-6 max-h-[85vh] flex flex-col"
      >
        <div className="flex items-start justify-between gap-3 mb-1">
          <h2
            id="attendee-access-title"
            className="text-lg font-bold text-[#0F1523]"
          >
            Attendees &amp; access
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="p-1 -mr-1 -mt-1 text-slate-400 hover:text-slate-700 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-xs text-[#777681] mb-4">
          {withAccess} of {rows.length} can open this meeting. Attending is
          what grants access, but only a confirmed identity counts — a name
          matched by guesswork does not.
        </p>

        {error && (
          <div className="flex items-start gap-2 p-2.5 mb-3 rounded-lg bg-red-50 border border-red-200">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-red-600" />
            <p className="text-xs text-red-700">{error}</p>
          </div>
        )}

        <div className="overflow-y-auto -mx-1 px-1 divide-y divide-gray-100">
          {rows.length === 0 && (
            <p className="text-xs text-[#777681] py-4">
              No attendees were recorded for this meeting.
            </p>
          )}
          {rows.map((row) => {
            const busy = busyId === row.id;
            const granted = !!row.grants_access;
            // Only offer a confirm when there is an account to confirm
            // against. Without a matching email there is nobody to link
            // to, and inventing one is not something to guess at.
            const canConfirm =
              !granted && !!row.suggested_user_id && canManage;

            return (
              <div key={row.id} className="flex items-center gap-3 py-2.5">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-[#0F1523] truncate">
                    {row.name}
                  </p>
                  <p className="text-[11px] text-[#777681] truncate">
                    {row.email || "no email recorded"}
                  </p>
                </div>

                {granted ? (
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 shrink-0"
                    title={`Linked via ${row.match_source}`}
                  >
                    <ShieldCheck className="w-3 h-3" />
                    Has access
                  </span>
                ) : (
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-slate-50 text-slate-600 border border-slate-200 shrink-0"
                    title={
                      row.match_source
                        ? `Matched by ${row.match_source}, which is not trusted for access`
                        : "Not linked to any account"
                    }
                  >
                    <ShieldOff className="w-3 h-3" />
                    No access
                  </span>
                )}

                {busy ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-500 shrink-0" />
                ) : granted && canManage ? (
                  <button
                    onClick={() => setLink(row, null)}
                    className="shrink-0 px-2 py-1 text-[11px] font-semibold text-slate-500 hover:text-red-600 rounded transition-colors"
                    title="Revoke this person's access to the meeting"
                  >
                    Unlink
                  </button>
                ) : canConfirm ? (
                  <button
                    onClick={() => setLink(row, row.suggested_user_id!)}
                    className="shrink-0 inline-flex items-center gap-1 px-2 py-1 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-50 rounded transition-colors"
                    title={`Confirm this is ${row.suggested_user_name}`}
                  >
                    <Check className="w-3 h-3" />
                    Confirm
                  </button>
                ) : (
                  <span
                    className="shrink-0 text-[11px] text-slate-400 px-2"
                    title={
                      canManage
                        ? "No account in this organization uses this email address"
                        : "Only an admin can change this"
                    }
                  >
                    {canManage ? "no account" : "—"}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {canManage && (
          <p className="text-[11px] text-[#777681] mt-4 pt-3 border-t border-gray-100">
            Confirming vouches for the identity, which is what makes the link
            count. It gives that person the transcript, its action items and
            its cards.
          </p>
        )}
      </div>
    </div>
  );
}
