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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import AuthShell from "../components/AuthShell";

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

  const canSubmit = email && password && !isLoading;

  return (
    <AuthShell
      eyebrow="Sign in"
      heading="Welcome back"
      subheading="Enter your details to access your workspace."
    >
      <form onSubmit={handleLogin} className="space-y-5">
        {error && (
          <div className="flex items-start gap-2.5 p-3 bg-red-50 border border-red-100 rounded-md">
            <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
            <p className="text-xs text-red-600 leading-relaxed">{error}</p>
          </div>
        )}

        <div className="space-y-1.5">
          <label
            htmlFor="email"
            className="block text-xs font-medium text-slate-700"
          >
            Email
          </label>
          <Input
            id="email"
            type="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={isLoading}
            className="h-10"
          />
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label
              htmlFor="password"
              className="block text-xs font-medium text-slate-700"
            >
              Password
            </label>
            <Link
              to="/forgot-password"
              className="text-xs text-slate-500 hover:text-indigo-600 transition-colors"
            >
              Forgot?
            </Link>
          </div>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={isLoading}
              className="h-10 pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              disabled={isLoading}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 disabled:opacity-50 transition-colors"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? (
                <EyeOff className="w-4 h-4" />
              ) : (
                <Eye className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>

        <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-500 hover:text-slate-900 transition-colors select-none">
          <input
            type="checkbox"
            checked={rememberMe}
            onChange={(e) => setRememberMe(e.target.checked)}
            disabled={isLoading}
            className="w-3.5 h-3.5 rounded border-slate-300 text-indigo-600 focus:ring-1 focus:ring-indigo-500 cursor-pointer disabled:opacity-50"
          />
          Keep me signed in
        </label>

        <Button
          type="submit"
          disabled={!canSubmit}
          className="w-full h-10 group"
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <>
              <span>Sign in</span>
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </>
          )}
        </Button>

        <p className="text-center text-xs text-slate-500 pt-2">
          Don't have an account?{" "}
          <Link
            to="/register"
            className="text-slate-900 hover:text-indigo-600 font-medium transition-colors"
          >
            Create one
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
