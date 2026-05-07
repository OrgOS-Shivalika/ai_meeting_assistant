import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authService } from "../../../services/authService";
import {
  Eye,
  EyeOff,
  Mail,
  Lock,
  Loader2,
  ArrowRight,
  AlertCircle,
} from "lucide-react";

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
    } catch (err) {
      setError("Invalid email or password. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const isFormValid = email && password && !isLoading;

  return (
    <div className="min-h-screen w-full bg-[#f0f2f5] flex items-center justify-center p-4 overflow-hidden relative">
      {/* Soft decorative blobs using primary color */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div
          className="absolute -top-1/2 -right-1/2 w-96 h-96 rounded-full blur-3xl animate-pulse"
          style={{ backgroundColor: "rgba(79,70,229,0.15)" }}
        />
        <div
          className="absolute -bottom-1/2 -left-1/2 w-96 h-96 rounded-full blur-3xl animate-pulse"
          style={{ backgroundColor: "rgba(79,70,229,0.1)", animationDelay: "1s" }}
        />
      </div>

      {/* Main container */}
      <div className="relative z-10 w-full max-w-md">
        {/* Logo/Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 bg-[#4F46E5] rounded-2xl mb-4 shadow-lg" style={{ boxShadow: "0 10px 25px -5px rgba(79,70,229,0.4)" }}>
            <svg
              className="w-8 h-8 text-white"
              fill="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-[#0F1523] mb-1">MeetingAI</h1>
          <p className="text-[#777681] text-sm">Welcome back to your workspace</p>
        </div>

        {/* Form Card */}
        <div className="bg-white rounded-2xl p-8 shadow-md border border-gray-200">
          <form onSubmit={handleLogin} className="space-y-5">
            {/* Error Alert */}
            {error && (
              <div className="flex items-start gap-3 p-4 bg-red-50 border border-red-200 rounded-lg animate-shake">
                <AlertCircle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
                <p className="text-sm text-red-600">{error}</p>
              </div>
            )}

            {/* Email Input */}
            <div className="space-y-1.5">
              <label
                htmlFor="email"
                className="block text-sm font-medium text-[#0F1523]"
              >
                Email Address
              </label>
              <div className="relative group">
                <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[#777681] group-focus-within:text-[#4F46E5] transition-colors" />
                <input
                  id="email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  disabled={isLoading}
                  className="w-full pl-12 pr-4 py-3 bg-gray-50 border border-gray-300 rounded-lg text-gray-900 placeholder:text-[#777681] focus:outline-none focus:ring-2 focus:ring-[#4F46E5] focus:border-transparent focus:bg-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>
            </div>

            {/* Password Input */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label
                  htmlFor="password"
                  className="block text-sm font-medium text-[#0F1523]"
                >
                  Password
                </label>
                <Link
                  to="/forgot-password"
                  className="text-xs text-[#4F46E5] hover:underline font-medium transition-colors"
                >
                  Forgot password?
                </Link>
              </div>
              <div className="relative group">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[#777681] group-focus-within:text-[#4F46E5] transition-colors" />
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  disabled={isLoading}
                  className="w-full pl-12 pr-12 py-3 bg-gray-50 border border-gray-300 rounded-lg text-gray-900 placeholder:text-[#777681] focus:outline-none focus:ring-2 focus:ring-[#4F46E5] focus:border-transparent focus:bg-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  disabled={isLoading}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-[#777681] hover:text-[#0F1523] transition-colors disabled:opacity-50"
                >
                  {showPassword ? (
                    <EyeOff className="w-5 h-5" />
                  ) : (
                    <Eye className="w-5 h-5" />
                  )}
                </button>
              </div>
            </div>

            {/* Remember Me */}
            <label className="flex items-center gap-2 cursor-pointer group">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                disabled={isLoading}
                className="w-4 h-4 bg-white border border-gray-300 rounded focus:ring-2 focus:ring-[#4F46E5] text-[#4F46E5] cursor-pointer disabled:opacity-50"
              />
              <span className="text-sm text-[#777681] group-hover:text-[#0F1523] transition-colors">
                Remember me
              </span>
            </label>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={!isFormValid}
              className="w-full mt-4 px-6 py-3 bg-[#4F46E5] hover:bg-[#4338CA] disabled:bg-[#777681] disabled:text-white/70 text-white font-semibold rounded-lg transition-all duration-200 flex items-center justify-center gap-2 shadow-md hover:shadow-lg disabled:shadow-none active:scale-95"
              style={{
                boxShadow: isFormValid ? "0 10px 25px -5px rgba(79,70,229,0.4)" : "none",
              }}
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Signing in...</span>
                </>
              ) : (
                <>
                  <span>Sign In</span>
                  <ArrowRight className="w-5 h-5" />
                </>
              )}
            </button>

            {/* Divider */}
            <div className="relative flex items-center gap-3 my-4">
              <div className="flex-1 h-px bg-[#777681]/20" />
              <span className="text-xs text-[#777681]">or</span>
              <div className="flex-1 h-px bg-[#777681]/20" />
            </div>

            {/* Sign Up Link */}
            <p className="text-center text-sm text-[#777681]">
              Don't have an account?{" "}
              <Link
                to="/register"
                className="text-[#4F46E5] hover:text-[#4338CA] font-semibold transition-colors"
              >
                Create one
              </Link>
            </p>
          </form>
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-[#777681] mt-6">
          By signing in, you agree to our{" "}
          <Link
            to="/terms"
            className="text-[#0F1523] hover:text-black underline"
          >
            Terms of Service
          </Link>
        </p>
      </div>
    </div>
  );
}