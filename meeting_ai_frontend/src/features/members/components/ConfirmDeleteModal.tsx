import { Trash2 } from "lucide-react";
import type { OrgMember } from "../api";
import { ROLE_LABEL } from "../roles";
import ConfirmDialog from "./ConfirmDialog";

/**
 * Confirmation for deleting an account.
 *
 * Spells out the consequences rather than just asking twice. Deleting a
 * person touches rows the admin didn't name — a category they created
 * changes hands, meetings they scheduled lose their creator link — and an
 * "Are you sure?" that hides that is not really a confirmation.
 */
export default function ConfirmDeleteModal({
  member,
  onClose,
  onConfirm,
}: {
  member: OrgMember;
  onClose: () => void;
  /** Resolves true when the delete landed; false keeps the dialog open. */
  onConfirm: () => Promise<boolean>;
}) {
  const scopeCount =
    member.managed_categories.length + member.managed_teams.length;

  return (
    <ConfirmDialog
      tone="danger"
      icon={Trash2}
      title="Delete this account?"
      subtitle={`${member.name} · ${member.email}`}
      warningHeading="This cannot be undone."
      warningDetail="There is no restore, and no way to recover the account's password or access afterwards. Re-adding this person creates a new account."
      confirmLabel="Delete account"
      confirmingLabel="Deleting"
      failureMessage="That did not go through. Nothing was deleted — see the message above the list."
      onClose={onClose}
      onConfirm={onConfirm}
      consequences={[
        <>
          Their sign-in is removed, along with their{" "}
          {ROLE_LABEL[member.access_role]} role
          {scopeCount > 0
            ? ` and ${scopeCount} category/team assignment${
                scopeCount === 1 ? "" : "s"
              }`
            : ""}
          .
        </>,
        member.meeting_count > 0 ? (
          <>
            The{" "}
            <strong className="font-semibold">
              {member.meeting_count} meeting
              {member.meeting_count === 1 ? "" : "s"}
            </strong>{" "}
            they attended stay, with their name still on the transcripts. Only
            the account link is dropped.
          </>
        ) : (
          <>No meeting history is affected — they have not attended any.</>
        ),
        <>
          Any category they created transfers to you, so it is not deleted along
          with them.
        </>,
        <>
          Their comments and task assignments remain, no longer attributed to
          anyone.
        </>,
      ]}
    />
  );
}
