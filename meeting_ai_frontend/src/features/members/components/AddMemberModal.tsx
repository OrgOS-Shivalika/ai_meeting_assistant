import { useState } from "react";
import {
  AlertCircle,
  Check,
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
} from "lucide-react";
import { membersApi, type CategoryRef, type CreateMemberResult } from "../api";
import GrantPicker, { type GrantSelection } from "./GrantPicker";
import { ROLE_LABEL, roleBadgeClass } from "../roles";
import type { AccessRole } from "../../auth/types";

/**
 * Two-step "Add Member" flow.
 *
 *   1. `form`   — email, password, role.
 *   2. `review` — the details read back, with the password shown and a
 *                 warning to copy it, and only then the create action.
 *
 * The review step is where the password lives because this is the only
 * moment it is ever visible: the server keeps a bcrypt hash, so once this
 * modal closes nobody — org admin included — can recover it. Showing it
 * before the write means the creator has copied it before an account
 * exists that depends on it.
 */
export default function AddMemberModal({
  categories,
  onClose,
  onCreated,
}: {
  categories: CategoryRef[];
  onClose: () => void;
  onCreated: (result: CreateMemberResult) => void;
}) {
  const [step, setStep] = useState<"form" | "review">("form");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AccessRole>("MEMBER");
  const [showPassword, setShowPassword] = useState(false);
  const [copied, setCopied] = useState(false);
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

  const emailLooksValid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  const passwordLongEnough = password.length >= 8;
  const canReview = emailLooksValid && passwordLongEnough;

  const copyPassword = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be blocked on http origins; the value is
      // select-all-able on screen as a fallback.
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const result = await membersApi.createMember({
        email: email.trim(),
        password,
        access_role: role,
      });
      // Grants are a second call: creation owns the credential, and
      // rolling the scope into it would mean a partial failure left an
      // account whose password was already shown but whose access is
      // wrong. This way a failed grant leaves a usable account that an
      // org admin can scope from the row editor.
      if (role === "ADMIN" && grantCount > 0) {
        await membersApi.update(result.user.id, {
          category_ids: grants.categoryIds,
          team_ids: grants.teamIds,
        });
      }
      onCreated(result);
    } catch (e: any) {
      setError(e?.message || "Could not create that member.");
      // Drop back to the form — the usual failure is a duplicate email,
      // and that is only fixable there.
      setStep("form");
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-lg max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-lg font-bold text-[#0F1523]">
            {step === "form" ? "Add Member" : "Review New Member"}
          </h2>
          <span className="text-xs font-semibold text-[#777681]">
            Step {step === "form" ? 1 : 2} of 2
          </span>
        </div>
        <p className="text-xs text-[#777681] mb-4">
          {step === "form"
            ? "Creates an account in your organization with the role you choose."
            : "Check these details, copy the password, then create the account."}
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

            <div className="mb-3">
              <label
                htmlFor="new-member-password"
                className="block text-xs font-semibold text-[#777681] mb-1.5"
              >
                Password
              </label>
              <div className="relative">
                <input
                  id="new-member-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  placeholder="At least 8 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-3 py-2 pr-10 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600"
                  title={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              </div>
              {password.length > 0 && !passwordLongEnough && (
                <p className="text-[11px] text-red-600 mt-1">
                  Must be at least 8 characters.
                </p>
              )}
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
                <option value="MEMBER">Member — meetings they attended</option>
                <option value="ADMIN">Admin — categories they manage</option>
                <option value="ORG_ADMIN">
                  Org Admin — the whole organization
                </option>
              </select>
              {role === "ADMIN" && (
                <div className="mt-2">
                  <p className="text-[11px] font-semibold text-[#777681] uppercase tracking-wide mb-1">
                    What they manage
                  </p>
                  <p className="text-[11px] text-[#777681] mb-2">
                    Tick a category for all of it, or expand it to grant
                    individual teams. An admin with nothing ticked sees
                    nothing.
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
            <dl className="rounded-lg border border-gray-200 divide-y divide-gray-100 mb-4">
              <div className="flex items-center justify-between px-3 py-2 gap-3">
                <dt className="text-xs font-semibold text-[#777681]">Email</dt>
                <dd className="text-sm text-[#0F1523] truncate">{email.trim()}</dd>
              </div>
              <div className="flex items-center justify-between px-3 py-2 gap-3">
                <dt className="text-xs font-semibold text-[#777681]">Role</dt>
                <dd
                  className={`px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wider ${roleBadgeClass(
                    role,
                  )}`}
                >
                  {ROLE_LABEL[role]}
                </dd>
              </div>
              <div className="flex items-center justify-between px-3 py-2 gap-3">
                <dt className="text-xs font-semibold text-[#777681]">Password</dt>
                <dd className="flex items-center gap-2 min-w-0">
                  <code className="px-2 py-0.5 rounded bg-slate-50 border border-gray-200 text-sm font-mono text-[#0F1523] select-all truncate">
                    {password}
                  </code>
                  <button
                    onClick={copyPassword}
                    className="flex items-center gap-1 px-2 py-1 shrink-0 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 rounded transition-colors"
                  >
                    {copied ? (
                      <Check className="w-3 h-3" />
                    ) : (
                      <Copy className="w-3 h-3" />
                    )}
                    {copied ? "Copied" : "Copy"}
                  </button>
                </dd>
              </div>
            </dl>

            {role === "ADMIN" && (
              <div className="rounded-lg border border-gray-200 px-3 py-2 mb-4">
                <p className="text-xs font-semibold text-[#777681] mb-1">
                  Manages
                </p>
                {grantCount === 0 ? (
                  <p className="text-[11px] text-amber-700">
                    Nothing selected — they will see no meetings until you
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

            <div className="flex items-start gap-2.5 p-3 mb-4 rounded-lg bg-amber-50 border border-amber-200">
              <KeyRound className="w-4 h-4 shrink-0 mt-0.5 text-amber-700" />
              <div>
                <p className="text-xs font-semibold text-amber-900">
                  Copy this password now
                </p>
                <p className="text-[11px] text-amber-800 mt-0.5">
                  This is the only time it will be visible. It is stored as a
                  one-way hash, so nobody — including you — can retrieve it
                  later. Share it over a channel you trust; they will be asked
                  to replace it when they first sign in.
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
