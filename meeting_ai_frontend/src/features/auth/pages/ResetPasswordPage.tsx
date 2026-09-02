import React, { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, ArrowRight, ShieldCheck } from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import { PUBLIC_PREFIX } from "../../../services/config";
import { withEncodedPasswords } from "../../../services/passwordTransport";
import { clearAuthFlag } from "../../../services/authFlag";
import { clearCurrentUser } from "../hooks/useCurrentUser";
import AuthShell, { AuthError, PasswordInput } from "../components/AuthShell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/label";

/**
 * "I forgot my password" — step two, reached from the emailed link.
 *
 * The token lives in the query string, which means it is also in the
 * browser's history and in any `Referer` this page emits. That is why the
 * server keeps it single-use and short-lived rather than trusting the URL to
 * stay private — this screen is the last place the raw token exists.
 *
 * Success does NOT sign anyone in. Controlling a mailbox is not the same as
 * controlling the account, and dropping someone straight into a live session
 * would turn a forwarded email into a full takeover. They land on the login
 * form and use the password they just set.
 */
export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";
  const navigate = useNavigate();

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [done, setDone] = useState(false);

  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;
  const tooShort = newPassword.length > 0 && newPassword.length < 8;
  const canSubmit = !!token && newPassword.length >= 8 && !mismatch && !isLoading;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await apiClient(`${PUBLIC_PREFIX}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Only the password goes through the base64 envelope — the token is
        // opaque and the server compares it as sent.
        body: JSON.stringify({
          token,
          ...withEncodedPasswords({ new_password: newPassword }, ["new_password"]),
        }),
      });
      // The reset revoked every session for this account, including any stale
      // one this browser is holding. Clear the local hints so the route guard
      // doesn't wave us into the app on a dead cookie.
      clearAuthFlag();
      clearCurrentUser();
      setDone(true);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Couldn't reset your password. The link may have expired.",
      );
    } finally {
      setIsLoading(false);
    }
  };

  // No token at all — someone opened /reset-password directly, or a mail
  // client mangled the link. Say so plainly rather than showing a form that
  // cannot succeed.
  if (!token) {
    return (
      <AuthShell
        eyebrow="Reset password"
        heading="This link is incomplete"
        subheading="The reset link is missing its token. It may have been cut short by your email client."
        variant="login"
      >
        <Button asChild className="w-full">
          <Link to="/forgot-password">
            Request a new link
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell
        eyebrow="Reset password"
        heading="Password updated"
        subheading="Sign in with your new password."
        variant="login"
      >
        <div className="flex flex-col gap-[18px]">
          <div className="flex items-start gap-3 rounded-md border border-hairline bg-surface-soft p-3.5">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" />
            <div className="text-[12px] leading-relaxed text-muted-ink">
              <p className="font-medium text-ink">
                You've been signed out everywhere else.
              </p>
              <p className="mt-1">
                Every other device and browser now needs the new password.
              </p>
            </div>
          </div>
          <Button onClick={() => navigate("/login")} className="w-full">
            Go to sign in
            <ArrowRight className="size-4" />
          </Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow="Reset password"
      heading="Choose a new password"
      subheading="At least 8 characters. You'll be signed out on your other devices."
      variant="login"
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-[18px]">
        {error && <AuthError>{error}</AuthError>}

        <Field label="New password" htmlFor="new-password">
          <PasswordInput
            id="new-password"
            placeholder="••••••••"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            autoFocus
            disabled={isLoading}
          />
          {tooShort && (
            <p className="mt-1.5 text-xs text-error">
              Use at least 8 characters.
            </p>
          )}
        </Field>

        <Field label="Confirm new password" htmlFor="confirm-password">
          <PasswordInput
            id="confirm-password"
            placeholder="••••••••"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            disabled={isLoading}
          />
          {mismatch && (
            <p className="mt-1.5 text-xs text-error">Passwords don't match.</p>
          )}
        </Field>

        <Button type="submit" disabled={!canSubmit} className="w-full">
          {isLoading ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Updating…
            </>
          ) : (
            <>
              Set new password
              <ArrowRight className="size-4" />
            </>
          )}
        </Button>

        <p className="text-center text-xs text-muted-ink">
          <Link to="/login" className="font-medium text-ink hover:underline">
            Back to sign in
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
