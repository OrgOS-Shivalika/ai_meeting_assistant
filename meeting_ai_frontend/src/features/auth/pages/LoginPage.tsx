import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authService } from "../../../services/authService";
import {
  Eye,
  EyeOff,
  Loader2,
  ArrowRight,
  AlertCircle,
} from "lucide-react";
import AuthShell, { VbButton, VbLabel, VbTextInput } from "../components/AuthShell";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await authService.login({ email, password });
      navigate("/");
    } catch {
      setError("Invalid email or password. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const canSubmit = !!email && !!password && !isLoading;

  return (
    <AuthShell
      eyebrow="Sign in"
      heading="Welcome back"
      subheading="Enter your details to access your workspace."
      variant="login"
    >
      <form onSubmit={handleLogin} className="flex flex-col gap-4.5">
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
          <VbLabel>Email</VbLabel>
          <VbTextInput
            id="email"
            type="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={isLoading}
          />
        </div>

        <div className="flex flex-col gap-1.75">
          <div className="flex items-center justify-between">
            <VbLabel>Password</VbLabel>
            <Link
              to="/forgot-password"
              className="transition-colors"
              style={{ fontSize: 12, color: "var(--vb-muted)" }}
            >
              Forgot?
            </Link>
          </div>
          <div className="relative">
            <VbTextInput
              id="password"
              type={showPassword ? "text" : "password"}
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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
        </div>

        <label
          className="flex items-center gap-2.5 cursor-pointer select-none"
          style={{ fontSize: 12, color: "var(--vb-muted)" }}
        >
          <input
            type="checkbox"
            checked={rememberMe}
            onChange={(e) => setRememberMe(e.target.checked)}
            disabled={isLoading}
            className="w-3.75 h-3.75 cursor-pointer disabled:opacity-50"
            style={{ accentColor: "var(--vb-ink)" }}
          />
          Keep me signed in
        </label>

        <VbButton type="submit" disabled={!canSubmit}>
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <>
              <span>Sign in</span>
              <ArrowRight className="w-4 h-4" />
            </>
          )}
        </VbButton>

        <p
          className="text-center"
          style={{ fontSize: 12, color: "var(--vb-muted)", marginTop: 6 }}
        >
          Don't have an account?{" "}
          <Link
            to="/register"
            style={{ color: "var(--vb-ink)", fontWeight: 600 }}
          >
            Create one
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
