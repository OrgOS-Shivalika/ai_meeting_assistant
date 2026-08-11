import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authService } from "../../../services/authService";
import { Loader2, ArrowRight, CheckCircle2, Check } from "lucide-react";
import AuthShell, {
  AuthCheckbox,
  AuthError,
  PasswordInput,
} from "../components/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Card } from "@/components/ui/card";

export default function RegisterPage() {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [agreeToTerms, setAgreeToTerms] = useState(false);
  const navigate = useNavigate();

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    if (error) setError("");
  };

  const validate = () => {
    if (!formData.name.trim()) return "Please enter your name";
    if (!formData.email.includes("@")) return "Please enter a valid email";
    if (formData.password.length < 8)
      return "Password must be at least 8 characters";
    if (formData.password !== formData.confirmPassword)
      return "Passwords do not match";
    if (!agreeToTerms) return "You must agree to the terms and conditions";
    return null;
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setError("");
    setIsLoading(true);
    try {
      await authService.register({
        name: formData.name,
        email: formData.email,
        password: formData.password,
      });
      setSuccess(true);
      setTimeout(() => navigate("/login"), 2000);
    } catch (err: any) {
      setError(err?.message || "Registration failed. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const canSubmit =
    !!formData.name &&
    !!formData.email &&
    !!formData.password &&
    !!formData.confirmPassword &&
    agreeToTerms &&
    !isLoading;

  const passwordMatch =
    formData.password === formData.confirmPassword && !!formData.password;
  const passwordStrong = formData.password.length >= 8;

  if (success) {
    return (
      <AuthShell
        eyebrow="Welcome"
        heading="You're in."
        subheading="Redirecting you to sign-in…"
        variant="register"
      >
        <Card variant="soft" padding="default" className="text-center">
          <CheckCircle2 className="mx-auto mb-3 size-10 text-success" />
          <p className="text-sm text-body">Your account is ready. One moment.</p>
          <div className="mt-5 h-0.5 w-full overflow-hidden rounded-full bg-hairline">
            <div className="h-full animate-pulse bg-ink" />
          </div>
        </Card>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow="Get started"
      heading="Create your account"
      subheading="Set up your workspace in under a minute."
      variant="register"
    >
      <form onSubmit={handleRegister} className="flex flex-col gap-4">
        {error && <AuthError>{error}</AuthError>}

        <Field label="Full name" htmlFor="name">
          <Input
            id="name"
            name="name"
            placeholder="Jane Doe"
            value={formData.name}
            onChange={handleChange}
            required
            disabled={isLoading}
          />
        </Field>

        <Field label="Work email" htmlFor="email">
          <Input
            id="email"
            name="email"
            type="email"
            placeholder="you@company.com"
            value={formData.email}
            onChange={handleChange}
            required
            disabled={isLoading}
          />
        </Field>

        <Field label="Password" htmlFor="password">
          <PasswordInput
            id="password"
            name="password"
            placeholder="At least 8 characters"
            value={formData.password}
            onChange={handleChange}
            required
            disabled={isLoading}
          />
          {formData.password && (
            <div className="flex items-center gap-1.5 pt-0.5">
              <div className="h-0.5 flex-1 overflow-hidden rounded-full bg-hairline">
                <div
                  className="h-full transition-all"
                  style={{
                    width: passwordStrong ? "100%" : "33%",
                    background: passwordStrong
                      ? "var(--vb-success)"
                      : "var(--vb-warning)",
                  }}
                />
              </div>
              <span className="font-mono text-[10px] text-muted-ink">
                {formData.password.length}/8
              </span>
            </div>
          )}
        </Field>

        <Field label="Confirm password" htmlFor="confirmPassword">
          <PasswordInput
            id="confirmPassword"
            name="confirmPassword"
            placeholder="Repeat password"
            value={formData.confirmPassword}
            onChange={handleChange}
            required
            disabled={isLoading}
          />
          {formData.confirmPassword && (
            <p
              className={`flex items-center gap-1 text-[11px] ${
                passwordMatch ? "text-success" : "text-error"
              }`}
            >
              {passwordMatch ? (
                <>
                  <Check className="size-3" /> Passwords match
                </>
              ) : (
                "Passwords do not match"
              )}
            </p>
          )}
        </Field>

        <AuthCheckbox
          checked={agreeToTerms}
          onChange={setAgreeToTerms}
          disabled={isLoading}
        >
          I agree to the{" "}
          <Link to="/terms" className="font-semibold text-ink">
            Terms
          </Link>{" "}
          and{" "}
          <Link to="/privacy" className="font-semibold text-ink">
            Privacy Policy
          </Link>
        </AuthCheckbox>

        <Button type="submit" disabled={!canSubmit} className="w-full">
          {isLoading ? (
            <Loader2 className="animate-spin" />
          ) : (
            <>
              <span>Create account</span>
              <ArrowRight />
            </>
          )}
        </Button>

        <p className="mt-1.5 text-center text-xs text-muted-ink">
          Already have an account?{" "}
          <Link to="/login" className="font-semibold text-ink">
            Sign in
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
