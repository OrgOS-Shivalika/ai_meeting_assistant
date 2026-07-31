import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authService } from "../../../services/authService";
import { Loader2, ArrowRight } from "lucide-react";
import AuthShell, {
  AuthCheckbox,
  AuthError,
  PasswordInput,
} from "../components/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
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
      <form onSubmit={handleLogin} className="flex flex-col gap-[18px]">
        {error && <AuthError>{error}</AuthError>}

        <Field label="Email" htmlFor="email">
          <Input
            id="email"
            type="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={isLoading}
          />
        </Field>

        <Field
          label="Password"
          htmlFor="password"
          action={
            <Link
              to="/forgot-password"
              className="text-xs text-muted-ink transition-colors hover:text-ink"
            >
              Forgot?
            </Link>
          }
        >
          <PasswordInput
            id="password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            disabled={isLoading}
          />
        </Field>

        <AuthCheckbox
          checked={rememberMe}
          onChange={setRememberMe}
          disabled={isLoading}
        >
          Keep me signed in
        </AuthCheckbox>

        <Button type="submit" disabled={!canSubmit} className="w-full">
          {isLoading ? (
            <Loader2 className="animate-spin" />
          ) : (
            <>
              <span>Sign in</span>
              <ArrowRight />
            </>
          )}
        </Button>

        <p className="mt-1.5 text-center text-xs text-muted-ink">
          Don't have an account?{" "}
          <Link to="/register" className="font-semibold text-ink">
            Create one
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
