import React, { useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, ArrowRight, MailCheck } from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import { PUBLIC_PREFIX } from "../../../services/config";
import AuthShell, { AuthError } from "../components/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";

/**
 * "I forgot my password" — step one.
 *
 * The confirmation is deliberately vague ("if an account exists…") and is
 * shown for EVERY address, including ones that plainly don't exist. That is
 * not hedging: a page that says "no account with that email" turns this form
 * into a membership checker for anyone who wants to know who is on the
 * platform. The server takes the same care; this screen must not undo it by
 * being more helpful.
 *
 * For the same reason there is no "resend" countdown driven by whether the
 * address was real. The server rate-limits per account, silently.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await apiClient(`${PUBLIC_PREFIX}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      setSubmitted(true);
    } catch {
      // Only reachable for a malformed address or an unreachable server —
      // the endpoint answers 202 for every well-formed request, real or not.
      setError("Couldn't send that request. Check the address and try again.");
    } finally {
      setIsLoading(false);
    }
  };

  if (submitted) {
    return (
      <AuthShell
        eyebrow="Reset password"
        heading="Check your email"
        subheading="If an account exists for that address, a reset link is on its way."
        variant="login"
      >
        <div className="flex flex-col gap-[18px]">
          <div className="flex items-start gap-3 rounded-md border border-hairline bg-surface-soft p-3.5">
            <MailCheck className="mt-0.5 size-4 shrink-0 text-success" />
            <div className="text-[12px] leading-relaxed text-muted-ink">
              <p className="font-medium text-ink">The link expires in 30 minutes.</p>
              <p className="mt-1">
                It works once. If it doesn't arrive, check your spam folder
                before asking for another.
              </p>
            </div>
          </div>
          <Button asChild className="w-full">
            <Link to="/login">
              Back to sign in
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow="Reset password"
      heading="Forgot your password?"
      subheading="Enter your email and we'll send you a link to set a new one."
      variant="login"
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-[18px]">
        {error && <AuthError>{error}</AuthError>}

        <Field label="Email" htmlFor="email">
          <Input
            id="email"
            type="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
            disabled={isLoading}
          />
        </Field>

        <Button type="submit" disabled={!email || isLoading} className="w-full">
          {isLoading ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Sending…
            </>
          ) : (
            <>
              Send reset link
              <ArrowRight className="size-4" />
            </>
          )}
        </Button>

        <p className="text-center text-xs text-muted-ink">
          Remembered it?{" "}
          <Link to="/login" className="font-medium text-ink hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
