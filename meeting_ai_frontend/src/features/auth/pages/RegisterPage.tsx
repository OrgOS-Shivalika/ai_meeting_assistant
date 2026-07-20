import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authService } from "../../../services/authService";
import {
  Eye,
  EyeOff,
  Loader2,
  ArrowRight,
  AlertCircle,
  CheckCircle2,
  Check,
} from "lucide-react";
import AuthShell, { VbButton, VbLabel, VbTextInput } from "../components/AuthShell";

export default function RegisterPage() {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
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
        <div
          className="rounded-lg p-6 text-center"
          style={{
            background: "var(--vb-surface-soft)",
            border: "1px solid var(--vb-hairline)",
          }}
        >
          <CheckCircle2
            className="w-10 h-10 mx-auto mb-3"
            style={{ color: "var(--vb-success)" }}
          />
          <p style={{ fontSize: 14, color: "var(--vb-body)" }}>
            Your account is ready. One moment.
          </p>
          <div
            className="mt-5 w-full h-0.5 rounded-full overflow-hidden"
            style={{ background: "var(--vb-hairline)" }}
          >
            <div
              className="h-full animate-pulse"
              style={{ background: "var(--vb-ink)" }}
            />
          </div>
        </div>
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

        <div className="flex flex-col gap-1.75">
          <VbLabel>Full name</VbLabel>
          <VbTextInput
            id="name"
            name="name"
            placeholder="Jane Doe"
            value={formData.name}
            onChange={handleChange}
            required
            disabled={isLoading}
          />
        </div>

        <div className="flex flex-col gap-1.75">
          <VbLabel>Work email</VbLabel>
          <VbTextInput
            id="email"
            name="email"
            type="email"
            placeholder="you@company.com"
            value={formData.email}
            onChange={handleChange}
            required
            disabled={isLoading}
          />
        </div>

        <div className="flex flex-col gap-1.75">
          <VbLabel>Password</VbLabel>
          <div className="relative">
            <VbTextInput
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              placeholder="At least 8 characters"
              value={formData.password}
              onChange={handleChange}
              required
              disabled={isLoading}
              style={{ paddingRight: 42 }}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              disabled={isLoading}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 disabled:opacity-50 transition-colors"
              style={{ color: "var(--vb-muted-soft)" }}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          {formData.password && (
            <div className="flex items-center gap-1.5 pt-0.5">
              <div
                className="flex-1 h-0.5 rounded-full overflow-hidden"
                style={{ background: "var(--vb-hairline)" }}
              >
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
              <span
                className="tabular-nums"
                style={{ fontSize: 10, color: "var(--vb-muted)" }}
              >
                {formData.password.length}/8
              </span>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-1.75">
          <VbLabel>Confirm password</VbLabel>
          <div className="relative">
            <VbTextInput
              id="confirmPassword"
              name="confirmPassword"
              type={showConfirm ? "text" : "password"}
              placeholder="Repeat password"
              value={formData.confirmPassword}
              onChange={handleChange}
              required
              disabled={isLoading}
              style={{ paddingRight: 42 }}
            />
            <button
              type="button"
              onClick={() => setShowConfirm((v) => !v)}
              disabled={isLoading}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 disabled:opacity-50 transition-colors"
              style={{ color: "var(--vb-muted-soft)" }}
              aria-label={showConfirm ? "Hide password" : "Show password"}
            >
              {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          {formData.confirmPassword && (
            <p
              className="flex items-center gap-1"
              style={{
                fontSize: 11,
                color: passwordMatch ? "var(--vb-success)" : "var(--vb-error)",
              }}
            >
              {passwordMatch ? (
                <>
                  <Check className="w-3 h-3" /> Passwords match
                </>
              ) : (
                "Passwords do not match"
              )}
            </p>
          )}
        </div>

        <label
          className="flex items-start gap-2.5 cursor-pointer select-none leading-relaxed"
          style={{ fontSize: 12, color: "var(--vb-muted)" }}
        >
          <input
            type="checkbox"
            checked={agreeToTerms}
            onChange={(e) => setAgreeToTerms(e.target.checked)}
            disabled={isLoading}
            className="w-3.75 h-3.75 mt-0.5 shrink-0 cursor-pointer disabled:opacity-50"
            style={{ accentColor: "var(--vb-ink)" }}
          />
          <span>
            I agree to the{" "}
            <Link
              to="/terms"
              style={{ color: "var(--vb-ink)", fontWeight: 600 }}
            >
              Terms
            </Link>{" "}
            and{" "}
            <Link
              to="/privacy"
              style={{ color: "var(--vb-ink)", fontWeight: 600 }}
            >
              Privacy Policy
            </Link>
          </span>
        </label>

        <VbButton type="submit" disabled={!canSubmit}>
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <>
              <span>Create account</span>
              <ArrowRight className="w-4 h-4" />
            </>
          )}
        </VbButton>

        <p
          className="text-center"
          style={{ fontSize: 12, color: "var(--vb-muted)", marginTop: 6 }}
        >
          Already have an account?{" "}
          <Link
            to="/login"
            style={{ color: "var(--vb-ink)", fontWeight: 600 }}
          >
            Sign in
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
