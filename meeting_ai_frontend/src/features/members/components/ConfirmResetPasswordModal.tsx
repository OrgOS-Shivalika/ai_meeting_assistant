import { useState } from "react";
import { KeyRound } from "lucide-react";
import type { OrgMember, ResetPasswordResult } from "../api";
import ConfirmDialog from "./ConfirmDialog";
import IssuedCredential from "./IssuedCredential";

/**
 * Issue a new temporary password: confirm, then read the result.
 *
 * Two phases in one dialog, because the value only exists for one render.
 * The server keeps a bcrypt hash, so the response is the single moment the
 * password is legible — closing on success and leaving it to a banner
 * behind would put the one thing the admin came for underneath whatever
 * they clicked next.
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
  /** Resolves the reset result, or null if it failed. */
  onConfirm: () => Promise<ResetPasswordResult | null>;
}) {
  const [issued, setIssued] = useState<ResetPasswordResult | null>(null);

  if (issued) {
    return (
      <IssuedCredential
        title="New password issued"
        email={member.email}
        password={issued.temporary_password}
        passwordLabel="Temporary password"
        emailStatus={issued.email_status}
        emailError={issued.email_error}
        sentDetail="They have been emailed the new password. Keep the copy below until they confirm they are back in — mail can bounce or be filtered."
        failedDetail="The password below is live regardless, and they are already signed out. Send it over a channel you trust."
        skippedDetail="No mail server is configured, so nothing was sent. Only a hash is stored, so nobody can look this up later — if it is lost, run the reset again to issue another."
        footer="They will be asked to replace it the next time they sign in, and until they do, the API refuses everything except signing in and setting a password."
        onClose={onClose}
      />
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
      // Stay open and hand over to `IssuedCredential` — the password cannot
      // be retrieved a second time.
      closeOnSuccess={false}
      onClose={onClose}
      onConfirm={async () => {
        const result = await onConfirm();
        if (result) setIssued(result);
        return !!result;
      }}
      consequences={[
        <>
          A new password is generated and emailed to them. You will see
          whether it actually went out.
        </>,
        <>
          It is also{" "}
          <strong className="font-semibold">shown to you once</strong>, as the
          fallback for when mail is not set up or does not arrive. It cannot
          be retrieved afterwards — if you miss it, run the reset again.
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
