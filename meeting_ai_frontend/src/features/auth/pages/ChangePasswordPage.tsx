import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertCircle, Loader2, ArrowRight } from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import { clearCurrentUser } from "../hooks/useCurrentUser";
import AuthShell, { VbButton, VbLabel, VbTextInput } from "../components/AuthShell";

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
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
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
      <form onSubmit={handleSubmit} className="flex flex-col gap-4.5">
        {error && (
          <div
            className="flex items-start gap-2.5 p-3 rounded-md"
            style={{
              background: "color-mix(in srgb, var(--vb-error) 8%, transparent)",
              border: "1px solid color-mix(in srgb, var(--vb-error) 25%, transparent)",
            }}
          >
            <AlertCircle
              className="w-4 h-4 shrink-0 mt-0.5"
              style={{ color: "var(--vb-error)" }}
            />
            <p className="text-xs leading-relaxed" style={{ color: "var(--vb-error)" }}>
              {error}
            </p>
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <VbLabel htmlFor="current-password">Current password</VbLabel>
          <VbTextInput
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setCurrentPassword(e.target.value)
            }
            placeholder="The password you signed in with"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <VbLabel htmlFor="new-password">New password</VbLabel>
          <VbTextInput
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setNewPassword(e.target.value)
            }
            placeholder="At least 8 characters"
          />
          {tooShort && (
            <p className="text-xs" style={{ color: "var(--vb-error)" }}>
              Must be at least 8 characters.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <VbLabel htmlFor="confirm-password">Confirm new password</VbLabel>
          <VbTextInput
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setConfirmPassword(e.target.value)
            }
            placeholder="Type it again"
          />
          {mismatch && (
            <p className="text-xs" style={{ color: "var(--vb-error)" }}>
              Passwords don't match.
            </p>
          )}
        </div>

        <VbButton type="submit" disabled={!canSubmit}>
          {isLoading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Saving
            </>
          ) : (
            <>
              Set password
              <ArrowRight className="w-4 h-4" />
            </>
          )}
        </VbButton>
      </form>
    </AuthShell>
  );
}
