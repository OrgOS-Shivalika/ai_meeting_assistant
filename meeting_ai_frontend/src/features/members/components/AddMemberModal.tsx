import { useEffect, useState } from "react";
import { AlertCircle, Loader2, Mail } from "lucide-react";
import { membersApi, type CategoryRef, type CreateMemberResult } from "../api";
import GrantPicker, { type GrantSelection } from "./GrantPicker";
import IssuedCredential from "./IssuedCredential";
import { ROLE_HINT, ROLE_LABEL, roleBadgeClass } from "../roles";
import { usePermissions } from "../../auth/hooks/usePermissions";
import type { AccessRole } from "../../auth/types";

const ROLE_ORDER: AccessRole[] = ["MEMBER", "ADMIN", "ORG_ADMIN"];

/**
 * Two-step "Add Member" flow.
 *
 *   1. `form`   — email, role, scope.
 *   2. `review` — the details read back, then the create action.
 *
 * There is no password field, and that is the change this flow exists
 * around. An admin choosing someone else's password means the account's
 * first credential is a secret another person knows and an email server
 * carried. The account is now created with a value nobody knows, and the
 * person sets their own via a single-use activation link.
 *
 * The third step still shows something once — the link, as a fallback for
 * when mail is unconfigured or bounces. It is a weaker thing to hold than
 * a password: single-use, time-limited, and it grants the admin nothing
 * they lacked, since they could re-invite the account anyway.
 */
export default function AddMemberModal({
  categories,
  onClose,
  onCreated,
}: {
  categories: CategoryRef[];
  onClose: () => void;
  /**
   * Fired once the account exists, so the caller can refresh its list.
   *
   * Does NOT mean "close me". The modal stays up on a third step to show
   * the activation link and whether the invite reached them — closing here
   * would put the only copy of that link behind whatever the admin clicked
   * next. Dismissal is `onClose`, from the Done button.
   */
  onCreated: (result: CreateMemberResult) => void;
}) {
  const [step, setStep] = useState<"form" | "review" | "result">("form");
  const [created, setCreated] = useState<CreateMemberResult | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<AccessRole>("MEMBER");
  // A category admin can create members and admins inside their own
  // categories, but not org admins — that role is scoped to nothing, so
  // the server refuses it. Don't list an option that can only 403.
  const { isOrgAdmin } = usePermissions();
  const roleOptions = isOrgAdmin
    ? ROLE_ORDER
    : ROLE_ORDER.filter((r) => r !== "ORG_ADMIN");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Only meaningful for ADMIN. Collected here so a new admin arrives with
  // a scope already attached — created without one they can see nothing,
  // which reads as the feature being broken.
  const [grants, setGrants] = useState<GrantSelection>({
    categoryIds: [],
    teamIds: [],
  });
  const grantCount = grants.categoryIds.length + grants.teamIds.length;

  // Escape closes, except mid-write: the request is already in flight and
  // the activation link it echoes back has to be shown, not dismissed.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [submitting, onClose]);

  const emailLooksValid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  // A category admin has to attach the new person to something they hold.
  // Created outside their scope, the account would be invisible to them
  // the moment it existed — the server refuses this for the same reason.
  const scopeRequired = !isOrgAdmin;
  const canReview =
    emailLooksValid && (!scopeRequired || grantCount > 0);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      // One request, account and scope together. This used to create the
      // account and then PATCH the grants, which failed for a category
      // admin: the new user holds no grant and has attended nothing, so
      // they are outside the creator's visible set until the first grant
      // exists, and the PATCH was refused with "That person is not in a
      // category you manage" — leaving an account nobody but an org admin
      // could reach. Sending both also makes it atomic, so a rejected
      // scope no longer leaves a stranded account.
      //
      // Grants are sent for MEMBER too. A scope is not a promotion — for a
      // member it is read access to those categories.
      const result = await membersApi.createMember({
        email: email.trim(),
        access_role: role,
        category_ids: grants.categoryIds,
        team_ids: grants.teamIds,
      });
      // Hand over to the result step rather than closing. `onCreated` still
      // fires so the list refreshes underneath, but the modal owns its own
      // dismissal now — the activation link and the invite outcome are both
      // in this response and neither can be fetched again.
      setCreated(result);
      setStep("result");
      setSubmitting(false);
      onCreated(result);
    } catch (e: any) {
      setError(e?.message || "Could not create that member.");
      // Drop back to the form — the usual failure is a duplicate email,
      // and that is only fixable there.
      setStep("form");
      setSubmitting(false);
    }
  };

  // Third step. Its own view rather than a branch inside the shell below,
  // because it shares nothing with the form: no backdrop dismissal, no
  // Escape, no Back — the reflexes that close a dialog are what would
  // destroy the only copy of the link.
  if (step === "result" && created) {
    return (
      <IssuedCredential
        title="Member invited"
        email={created.user.email}
        value={created.invite_url}
        valueLabel="Activation link"
        emailStatus={created.email_status}
        emailError={created.email_error}
        sentDetail="They have been emailed a link to set their own password. Keep the copy below until they confirm they are in — a wrong address is accepted by the mail server and only bounces later."
        failedDetail="The account exists but the invitation did not send. Pass the link below on over a channel you trust."
        skippedDetail="No mail server is configured, so nothing was sent. Send them the link below — if it is lost or expires, add them again or reset their password to issue a new one."
        footer="The link works once and expires in 7 days. They choose their own password — nobody here, including you, ever sees it."
        extra={
          created.linked_meetings > 0 ? (
            <div className="rounded-lg border border-gray-200 px-3 py-2 mb-4">
              <p className="text-[11px] text-slate-700">
                Linked to{" "}
                <strong className="font-semibold">
                  {created.linked_meetings} meeting
                  {created.linked_meetings === 1 ? "" : "s"}
                </strong>{" "}
                they had already attended — they can see those straight away.
              </p>
            </div>
          ) : null
        }
        onClose={onClose}
      />
    );
  }

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={() => !submitting && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-member-title"
        onClick={(e) => e.stopPropagation()}
        className="bg-canvas rounded-lg shadow-soft max-w-md w-full p-6"
      >
        <div className="flex items-center justify-between mb-1">
          <h2 id="add-member-title" className="text-lg font-semibold text-[#0F1523]">
            {step === "form" ? "Add Member" : "Review New Member"}
          </h2>
          <span className="text-xs font-semibold text-[#777681]">
            Step {step === "form" ? 1 : 2} of 2
          </span>
        </div>
        <p className="text-xs text-[#777681] mb-4">
          {step === "form"
            ? "Creates an account in your organization and emails them their sign-in details."
            : "Check the address carefully — the invite is sent the moment you create the account."}
        </p>

        {error && (
          <div className="flex items-start gap-2 p-2.5 mb-3 rounded-lg bg-red-50 border border-red-200">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-red-600" />
            <p className="text-xs text-red-700">{error}</p>
          </div>
        )}

        {step === "form" ? (
          <>
            <div className="mb-3">
              <label
                htmlFor="new-member-email"
                className="block text-xs font-semibold text-[#777681] mb-1.5"
              >
                Email
              </label>
              <input
                id="new-member-email"
                type="email"
                autoComplete="off"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
              />
              {email.length > 0 && !emailLooksValid && (
                <p className="text-[11px] text-red-600 mt-1">
                  That does not look like an email address.
                </p>
              )}
              <p className="text-[11px] text-[#777681] mt-1">
                Use the address on their calendar invitations — that is how past
                meetings get linked to this account.
              </p>
            </div>

            <div className="mb-4">
              <label
                htmlFor="new-member-role"
                className="block text-xs font-semibold text-[#777681] mb-1.5"
              >
                Role
              </label>
              <select
                id="new-member-role"
                value={role}
                onChange={(e) => setRole(e.target.value as AccessRole)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
              >
                {roleOptions.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABEL[r]} — {ROLE_HINT[r].toLowerCase()}
                  </option>
                ))}
              </select>
              {/* Offered for MEMBER as well as ADMIN. The scope is the same
                  choice either way — which categories and teams this person
                  is attached to — and only the role decides whether that
                  means reading them or running them. */}
              {role !== "ORG_ADMIN" && (
                <div className="mt-2">
                  <p className="text-[11px] font-semibold text-[#777681] uppercase tracking-wide mb-1">
                    {role === "ADMIN" ? "What they manage" : "What they can see"}
                  </p>
                  <p className="text-[11px] text-[#777681] mb-2">
                    Tick a category for all of it, or expand it to pick
                    individual teams.{" "}
                    {scopeRequired
                      ? "Required — you can only add people to the categories you manage."
                      : role === "ADMIN"
                        ? "An admin with nothing ticked manages nothing."
                        : "Optional — a member always sees the meetings they attended."}
                  </p>
                  <div className="max-h-48 overflow-y-auto pr-1">
                    <GrantPicker
                      categories={categories}
                      value={grants}
                      onChange={setGrants}
                    />
                  </div>
                </div>
              )}
              {role === "ORG_ADMIN" && (
                <p className="text-[11px] text-amber-700 mt-1">
                  Org admins can read and manage every meeting, task and board
                  in the organization.
                </p>
              )}
            </div>

            <div className="flex gap-3">
              <button
                onClick={onClose}
                className="flex-1 px-4 py-2 border border-gray-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setError(null);
                  setStep("review");
                }}
                disabled={!canReview}
                className="flex-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white rounded-lg text-sm font-semibold transition-colors"
              >
                Review
              </button>
            </div>
          </>
        ) : (
          <>
            <dl className="rounded-lg border border-gray-200 divide-y divide-hairline-soft mb-4">
              <div className="flex items-center justify-between px-3 py-2 gap-3">
                <dt className="text-xs font-semibold text-[#777681]">Email</dt>
                <dd className="text-sm text-[#0F1523] truncate">{email.trim()}</dd>
              </div>
              <div className="flex items-center justify-between px-3 py-2 gap-3">
                <dt className="text-xs font-semibold text-[#777681]">Role</dt>
                <dd
                  className={`px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider ${roleBadgeClass(
                    role,
                  )}`}
                >
                  {ROLE_LABEL[role]}
                </dd>
              </div>
            </dl>

            {/* Members get a scope summary too — it is the same review
                step, and omitting it made a member's assigned scope
                invisible right where it should be confirmed. */}
            {role !== "ORG_ADMIN" && (grantCount > 0 || role === "ADMIN") && (
              <div className="rounded-lg border border-gray-200 px-3 py-2 mb-4">
                <p className="text-xs font-semibold text-[#777681] mb-1">
                  {role === "ADMIN" ? "Manages" : "Can see"}
                </p>
                {grantCount === 0 ? (
                  <p className="text-[11px] text-amber-700">
                    Nothing selected — they will manage nothing until you
                    assign categories or teams.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {categories
                      .filter((c) => grants.categoryIds.includes(c.id))
                      .map((c) => (
                        <span
                          key={`c-${c.id}`}
                          className="px-2 py-0.5 rounded text-[11px] bg-indigo-50 text-indigo-700 border border-indigo-100"
                        >
                          {c.name}
                        </span>
                      ))}
                    {categories.flatMap((c) =>
                      (c.teams ?? [])
                        .filter((t) => grants.teamIds.includes(t.id))
                        .map((t) => (
                          <span
                            key={`t-${t.id}`}
                            className="px-2 py-0.5 rounded text-[11px] bg-slate-50 text-slate-700 border border-slate-200"
                          >
                            {c.name} › {t.name}
                          </span>
                        )),
                    )}
                  </div>
                )}
              </div>
            )}

            {/* What happens on "Create Member", stated before it happens —
                the reset flow does the same on its confirm step. No "copy
                the password anyway" panel any more: there is no password to
                copy, which is the entire point of the change. */}
            <div className="flex items-start gap-2.5 p-3 mb-4 rounded-lg bg-indigo-50 border border-indigo-200">
              <Mail className="w-4 h-4 shrink-0 mt-0.5 text-indigo-700" />
              <div>
                <p className="text-xs font-semibold text-indigo-900">
                  They'll be emailed an invitation
                </p>
                <p className="text-[11px] text-indigo-800 mt-0.5">
                  A link to set their own password goes to{" "}
                  <span className="font-medium">{email.trim()}</span> as soon as
                  you create the account, and you'll be told whether it actually
                  sent. Nobody here ever sees the password they choose — and if
                  the mail does not arrive, you'll get the link to pass on.
                </p>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setStep("form")}
                disabled={submitting}
                className="flex-1 px-4 py-2 border border-gray-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
              >
                Back
              </button>
              <button
                onClick={submit}
                disabled={submitting}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white rounded-lg text-sm font-semibold transition-colors"
              >
                {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Create Member
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
