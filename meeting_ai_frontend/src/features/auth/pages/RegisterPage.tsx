import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authService } from "../../../services/authService";
import {
  Eye,
  EyeOff,
  Mail,
  Lock,
  User,
  Loader2,
  ArrowRight,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";

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
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [agreeToTerms, setAgreeToTerms] = useState(false);
  const navigate = useNavigate();

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    setError("");
  };

  const validateForm = () => {
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
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
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
    } catch (err) {
      setError("Registration failed. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const isFormValid =
    formData.name &&
    formData.email &&
    formData.password &&
    formData.confirmPassword &&
    agreeToTerms &&
    !isLoading;

  const passwordMatch =
    formData.password === formData.confirmPassword && formData.password;
  const passwordStrong = formData.password.length >= 8;

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
          <div
            className="inline-flex items-center justify-center w-14 h-14 bg-[#4F46E5] rounded-2xl mb-4 shadow-lg"
            style={{ boxShadow: "0 10px 25px -5px rgba(79,70,229,0.4)" }}
          >
            <svg
              className="w-8 h-8 text-white"
              fill="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-[#0F1523] mb-1">MeetingAI</h1>
          <p className="text-[#777681] text-sm">
            Join thousands of teams using intelligent meeting insights
          </p>
        </div>

        {/* Success State */}
        {success && (
          <div className="bg-white rounded-2xl p-8 shadow-md border border-gray-200 text-center animate-fadeIn">
            <CheckCircle2 className="w-16 h-16 text-green-500 mx-auto mb-4" />
            <h2 className="text-xl font-bold text-[#0F1523] mb-2">Welcome!</h2>
            <p className="text-[#777681] mb-6">
              Your account has been created successfully. Redirecting to
              login...
            </p>
            <div className="w-full h-1 bg-gray-200 rounded-full overflow-hidden">
              <div className="h-full bg-[#4F46E5] animate-pulse" />
            </div>
          </div>
        )}

        {/* Form Card */}
        {!success && (
          <div className="bg-white rounded-2xl p-8 shadow-md border border-gray-200">
            <form onSubmit={handleRegister} className="space-y-5">
              {/* Error Alert */}
              {error && (
                <div className="flex items-start gap-3 p-4 bg-red-50 border border-red-200 rounded-lg animate-shake">
                  <AlertCircle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
                  <p className="text-sm text-red-600">{error}</p>
                </div>
              )}

              {/* Name Input */}
              <div className="space-y-1.5">
                <label
                  htmlFor="name"
                  className="block text-sm font-medium text-[#0F1523]"
                >
                  Full Name
                </label>
                <div className="relative group">
                  <User className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[#777681] group-focus-within:text-[#4F46E5] transition-colors" />
                  <input
                    id="name"
                    name="name"
                    type="text"
                    placeholder="John Doe"
                    value={formData.name}
                    onChange={handleChange}
                    required
                    disabled={isLoading}
                    className="w-full pl-12 pr-4 py-3 bg-gray-50 border border-gray-300 rounded-lg text-gray-900 placeholder:text-[#777681] focus:outline-none focus:ring-2 focus:ring-[#4F46E5] focus:border-transparent focus:bg-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                </div>
              </div>

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
                    name="email"
                    type="email"
                    placeholder="you@example.com"
                    value={formData.email}
                    onChange={handleChange}
                    required
                    disabled={isLoading}
                    className="w-full pl-12 pr-4 py-3 bg-gray-50 border border-gray-300 rounded-lg text-gray-900 placeholder:text-[#777681] focus:outline-none focus:ring-2 focus:ring-[#4F46E5] focus:border-transparent focus:bg-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                </div>
              </div>

              {/* Password Input */}
              <div className="space-y-1.5">
                <label
                  htmlFor="password"
                  className="block text-sm font-medium text-[#0F1523]"
                >
                  Password
                </label>
                <div className="relative group">
                  <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[#777681] group-focus-within:text-[#4F46E5] transition-colors" />
                  <input
                    id="password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={formData.password}
                    onChange={handleChange}
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
                <div className="flex items-center gap-2 mt-1">
                  <div
                    className={`h-1 flex-1 rounded-full transition-colors ${
                      passwordStrong ? "bg-green-500" : "bg-gray-200"
                    }`}
                  />
                  <span className="text-xs text-[#777681]">
                    {formData.password.length === 0
                      ? "0"
                      : formData.password.length}
                    + chars
                  </span>
                </div>
              </div>

              {/* Confirm Password Input */}
              <div className="space-y-1.5">
                <label
                  htmlFor="confirmPassword"
                  className="block text-sm font-medium text-[#0F1523]"
                >
                  Confirm Password
                </label>
                <div className="relative group">
                  <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[#777681] group-focus-within:text-[#4F46E5] transition-colors" />
                  <input
                    id="confirmPassword"
                    name="confirmPassword"
                    type={showConfirmPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={formData.confirmPassword}
                    onChange={handleChange}
                    required
                    disabled={isLoading}
                    className="w-full pl-12 pr-12 py-3 bg-gray-50 border border-gray-300 rounded-lg text-gray-900 placeholder:text-[#777681] focus:outline-none focus:ring-2 focus:ring-[#4F46E5] focus:border-transparent focus:bg-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    disabled={isLoading}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-[#777681] hover:text-[#0F1523] transition-colors disabled:opacity-50"
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="w-5 h-5" />
                    ) : (
                      <Eye className="w-5 h-5" />
                    )}
                  </button>
                </div>
                {formData.confirmPassword && (
                  <p
                    className={`text-xs ${
                      passwordMatch ? "text-green-600" : "text-red-500"
                    }`}
                  >
                    {passwordMatch
                      ? "✓ Passwords match"
                      : "✗ Passwords do not match"}
                  </p>
                )}
              </div>

              {/* Terms Checkbox */}
              <label className="flex items-start gap-3 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={agreeToTerms}
                  onChange={(e) => setAgreeToTerms(e.target.checked)}
                  disabled={isLoading}
                  className="w-4 h-4 bg-white border border-gray-300 rounded focus:ring-2 focus:ring-[#4F46E5] text-[#4F46E5] cursor-pointer disabled:opacity-50 mt-1"
                />
                <span className="text-sm text-[#777681] group-hover:text-[#0F1523] transition-colors">
                  I agree to the{" "}
                  <Link
                    to="/terms"
                    className="text-[#4F46E5] hover:text-[#4338CA] font-medium"
                  >
                    Terms of Service
                  </Link>{" "}
                  and{" "}
                  <Link
                    to="/privacy"
                    className="text-[#4F46E5] hover:text-[#4338CA] font-medium"
                  >
                    Privacy Policy
                  </Link>
                </span>
              </label>

              {/* Submit Button */}
              <button
                type="submit"
                disabled={!isFormValid}
                className="w-full mt-6 px-6 py-3 bg-[#4F46E5] hover:bg-[#4338CA] disabled:bg-[#777681] disabled:text-white/70 text-white font-semibold rounded-lg transition-all duration-200 flex items-center justify-center gap-2 shadow-md hover:shadow-lg disabled:shadow-none active:scale-95"
                style={{
                  boxShadow: isFormValid
                    ? "0 10px 25px -5px rgba(79,70,229,0.4)"
                    : "none",
                }}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Creating account...</span>
                  </>
                ) : (
                  <>
                    <span>Create Account</span>
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>

              {/* Sign In Link */}
              <p className="text-center text-sm text-[#777681]">
                Already have an account?{" "}
                <Link
                  to="/login"
                  className="text-[#4F46E5] hover:text-[#4338CA] font-semibold transition-colors"
                >
                  Sign in
                </Link>
              </p>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}