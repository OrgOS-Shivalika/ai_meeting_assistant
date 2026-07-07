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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import AuthShell from "../components/AuthShell";

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
    formData.name &&
    formData.email &&
    formData.password &&
    formData.confirmPassword &&
    agreeToTerms &&
    !isLoading;

  const passwordMatch =
    formData.password === formData.confirmPassword && formData.password;
  const passwordStrong = formData.password.length >= 8;

  if (success) {
    return (
      <AuthShell
        eyebrow="Welcome"
        heading="You're in."
        subheading="Redirecting you to sign-in…"
      >
        <div className="rounded-lg border border-slate-200 p-6 text-center bg-slate-50/50">
          <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto mb-3" />
          <p className="text-sm text-slate-600">
            Your account is ready. One moment.
          </p>
          <div className="mt-5 w-full h-0.5 bg-slate-200 rounded-full overflow-hidden">
            <div className="h-full bg-indigo-600 animate-pulse" />
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
    >
      <form onSubmit={handleRegister} className="space-y-5">
        {error && (
          <div className="flex items-start gap-2.5 p-3 bg-red-50 border border-red-100 rounded-md">
            <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
            <p className="text-xs text-red-600 leading-relaxed">{error}</p>
          </div>
        )}

        <div className="space-y-1.5">
          <label
            htmlFor="name"
            className="block text-xs font-medium text-slate-700"
          >
            Full name
          </label>
          <Input
            id="name"
            name="name"
            placeholder="Jane Doe"
            value={formData.name}
            onChange={handleChange}
            required
            disabled={isLoading}
            className="h-10"
          />
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="email"
            className="block text-xs font-medium text-slate-700"
          >
            Work email
          </label>
          <Input
            id="email"
            name="email"
            type="email"
            placeholder="you@company.com"
            value={formData.email}
            onChange={handleChange}
            required
            disabled={isLoading}
            className="h-10"
          />
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="password"
            className="block text-xs font-medium text-slate-700"
          >
            Password
          </label>
          <div className="relative">
            <Input
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              placeholder="At least 8 characters"
              value={formData.password}
              onChange={handleChange}
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
          {formData.password && (
            <div className="flex items-center gap-1.5 pt-0.5">
              <div className="flex-1 h-0.5 bg-slate-200 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all ${
                    passwordStrong
                      ? "w-full bg-emerald-500"
                      : "w-1/3 bg-amber-400"
                  }`}
                />
              </div>
              <span className="text-[10px] text-slate-500 tabular-nums">
                {formData.password.length}/8
              </span>
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="confirmPassword"
            className="block text-xs font-medium text-slate-700"
          >
            Confirm password
          </label>
          <div className="relative">
            <Input
              id="confirmPassword"
              name="confirmPassword"
              type={showConfirm ? "text" : "password"}
              placeholder="Repeat password"
              value={formData.confirmPassword}
              onChange={handleChange}
              required
              disabled={isLoading}
              className="h-10 pr-10"
            />
            <button
              type="button"
              onClick={() => setShowConfirm((v) => !v)}
              disabled={isLoading}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 disabled:opacity-50 transition-colors"
              aria-label={showConfirm ? "Hide password" : "Show password"}
            >
              {showConfirm ? (
                <EyeOff className="w-4 h-4" />
              ) : (
                <Eye className="w-4 h-4" />
              )}
            </button>
          </div>
          {formData.confirmPassword && (
            <p
              className={`text-[11px] flex items-center gap-1 ${
                passwordMatch ? "text-emerald-600" : "text-red-500"
              }`}
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

        <label className="flex items-start gap-2 cursor-pointer text-xs text-slate-500 hover:text-slate-900 transition-colors select-none">
          <input
            type="checkbox"
            checked={agreeToTerms}
            onChange={(e) => setAgreeToTerms(e.target.checked)}
            disabled={isLoading}
            className="w-3.5 h-3.5 rounded border-slate-300 text-indigo-600 focus:ring-1 focus:ring-indigo-500 cursor-pointer disabled:opacity-50 mt-0.5"
          />
          <span className="leading-relaxed">
            I agree to the{" "}
            <Link
              to="/terms"
              className="text-slate-900 hover:text-indigo-600 font-medium"
            >
              Terms
            </Link>{" "}
            and{" "}
            <Link
              to="/privacy"
              className="text-slate-900 hover:text-indigo-600 font-medium"
            >
              Privacy Policy
            </Link>
          </span>
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
              <span>Create account</span>
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </>
          )}
        </Button>

        <p className="text-center text-xs text-slate-500 pt-2">
          Already have an account?{" "}
          <Link
            to="/login"
            className="text-slate-900 hover:text-indigo-600 font-medium transition-colors"
          >
            Sign in
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
