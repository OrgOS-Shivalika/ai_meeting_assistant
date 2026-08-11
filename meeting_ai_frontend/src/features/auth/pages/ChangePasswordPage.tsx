import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, ArrowRight } from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import { withEncodedPasswords } from "../../../services/passwordTransport";
import { clearCurrentUser } from "../hooks/useCurrentUser";
import AuthShell, { AuthError, PasswordInput } from "../components/AuthShell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/label";

/**
 * Set a new password.
 *
 * Doubles as the landing page for an admin provisioned by an org admin:
 * they sign in with a generated password, the backend answers 403 on
 * everything except `/auth/me`, `/auth/change-password` and `/auth/logout`,
 * and this is where they get out of that state.
 */
export default function ChangePasswordPage() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;
  const tooShort = newPassword.length > 0 && newPassword.length < 8;
  const canSubmit =
    !!currentPassword && newPassword.length >= 8 && !mismatch && !isLoading;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await apiClient("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Both passwords are base64-encoded in transit; the backend always
        // decodes, then checks the 8-character floor against the decoded
        // value.
        body: JSON.stringify(
          withEncodedPasswords(
            {
              current_password: currentPassword,
              new_password: newPassword,
            },
            ["current_password", "new_password"],
          ),
        ),
      });
      // `must_change_password` just flipped, so the cached /auth/me is
      // stale — drop it or the app keeps redirecting back here.
      clearCurrentUser();
      navigate("/");
    } catch (err: any) {
      setError(err?.message || "Could not change your password. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthShell
      eyebrow="Security"
      heading="Set a new password"
      subheading="Choose a password only you know before continuing."
      variant="login"
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-[18px]">
        {error && <AuthError>{error}</AuthError>}

        <Field label="Current password" htmlFor="current-password">
          <PasswordInput
            id="current-password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            placeholder="The password you signed in with"
          />
        </Field>

        <Field
          label="New password"
          htmlFor="new-password"
          error={tooShort ? "Must be at least 8 characters." : undefined}
        >
          <PasswordInput
            id="new-password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="At least 8 characters"
          />
        </Field>

        <Field
          label="Confirm new password"
          htmlFor="confirm-password"
          error={mismatch ? "Passwords don't match." : undefined}
        >
          <PasswordInput
            id="confirm-password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Type it again"
          />
        </Field>

        <Button type="submit" disabled={!canSubmit} className="w-full">
          {isLoading ? (
            <>
              <Loader2 className="animate-spin" />
              Saving
            </>
          ) : (
            <>
              Set password
              <ArrowRight />
            </>
          )}
        </Button>
      </form>
    </AuthShell>
  );
}
