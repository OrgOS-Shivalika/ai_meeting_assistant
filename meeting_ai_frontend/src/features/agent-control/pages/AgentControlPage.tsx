import { useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ExternalLink,
  Loader2,
  LogOut,
  RefreshCw,
  Zap,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { apiClient } from "../../../services/apiClient";
import { authService } from "../../../services/authService";

interface GoogleStatus {
  is_connected: boolean;
  google_info?: {
    email?: string;
    name?: string;
    picture?: string;
  } | null;
}

export default function AgentControlPage() {
  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const data: GoogleStatus = await apiClient("/auth/google/status");
      setStatus(data);
    } catch (err) {
      console.error("Failed to load Google status", err);
      setError("Couldn't load calendar connection status.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    setError("");
    try {
      const data = await authService.getGoogleAuthUrl();
      if (data.auth_url) {
        window.location.href = data.auth_url;
        return;
      }
      setError("No auth URL returned by the server.");
    } catch (err) {
      console.error("Failed to start Google OAuth", err);
      setError("Failed to start Google connection.");
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (
      !window.confirm(
        "Disconnect Google Calendar? Scheduled meetings stop syncing to your calendar until you reconnect.",
      )
    ) {
      return;
    }
    setDisconnecting(true);
    setError("");
    try {
      await apiClient("/auth/google/disconnect", { method: "POST" });
      setStatus({ is_connected: false, google_info: null });
    } catch (err) {
      console.error("Failed to disconnect Google", err);
      setError("Failed to disconnect. Please try again.");
    } finally {
      setDisconnecting(false);
    }
  };

  const isConnected = !!status?.is_connected;
  const info = status?.google_info ?? null;

  return (
    <Layout>
      <div className="max-w-5xl mx-auto px-4 py-6 space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-indigo-50 rounded-xl">
              <Zap className="w-5 h-5 text-indigo-600 fill-indigo-600/10" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
                Agent Control
              </h1>
              <p className="text-sm text-slate-500">
                Manage what your meeting agent can see and do on your behalf.
              </p>
            </div>
          </div>
          <button
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-3 p-4 bg-rose-50 border border-rose-100 rounded-xl">
            <AlertCircle className="w-5 h-5 text-rose-500 shrink-0" />
            <p className="text-sm text-rose-700 font-medium">{error}</p>
          </div>
        )}

        {/* Integrations section */}
        <section>
          <div className="flex items-end justify-between mb-3">
            <div>
              <h2 className="text-sm font-bold text-slate-900 uppercase tracking-widest">
                Integrations
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Authorise the agent to read and write on your connected accounts.
              </p>
            </div>
          </div>

          {/* Google Calendar card */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="p-6 flex flex-col md:flex-row md:items-center justify-between gap-6">
              <div className="flex items-start gap-4 min-w-0">
                <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center shrink-0">
                  <Calendar className="w-6 h-6 text-blue-600" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-base font-bold text-slate-900">
                      Google Calendar
                    </h3>
                    {loading ? (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-slate-50 text-slate-500 text-[10px] font-bold rounded-full ring-1 ring-slate-200">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Checking…
                      </span>
                    ) : isConnected ? (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-emerald-50 text-emerald-700 text-[10px] font-bold rounded-full ring-1 ring-emerald-200">
                        <CheckCircle2 className="w-3 h-3" />
                        Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-amber-50 text-amber-700 text-[10px] font-bold rounded-full ring-1 ring-amber-200">
                        <AlertCircle className="w-3 h-3" />
                        Not connected
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                    Lets the agent auto-join scheduled events, create calendar
                    invites for meetings you schedule here, and surface upcoming
                    meetings in the dashboard.
                  </p>

                  {isConnected && info && (
                    <div className="flex items-center gap-3 mt-4 p-3 rounded-xl bg-slate-50 border border-slate-100">
                      {info.picture ? (
                        <img
                          src={info.picture}
                          alt={info.name || info.email || "Profile"}
                          className="w-9 h-9 rounded-lg ring-1 ring-slate-200"
                        />
                      ) : (
                        <div className="w-9 h-9 rounded-lg bg-white ring-1 ring-slate-200 flex items-center justify-center text-sm font-bold text-slate-500">
                          {(info.name || info.email || "?").charAt(0).toUpperCase()}
                        </div>
                      )}
                      <div className="min-w-0">
                        <p className="text-sm font-bold text-slate-800 truncate">
                          {info.name || "Google account"}
                        </p>
                        <p className="text-xs text-slate-500 truncate">
                          {info.email || ""}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {isConnected ? (
                  <>
                    <a
                      href="/calendar"
                      className="flex items-center gap-2 px-3 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50 rounded-lg border border-slate-200 transition-colors"
                    >
                      <ExternalLink className="w-4 h-4" />
                      View calendar
                    </a>
                    <button
                      onClick={handleDisconnect}
                      disabled={disconnecting}
                      className="flex items-center gap-2 px-3 py-2 text-sm font-bold text-rose-600 hover:bg-rose-50 rounded-lg border border-transparent hover:border-rose-100 transition-colors disabled:opacity-50"
                    >
                      <LogOut className="w-4 h-4" />
                      {disconnecting ? "Disconnecting…" : "Disconnect"}
                    </button>
                  </>
                ) : (
                  <button
                    onClick={handleConnect}
                    disabled={connecting || loading}
                    className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-bold shadow-md shadow-indigo-600/20 transition-all active:scale-[0.98] disabled:opacity-50"
                  >
                    {connecting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Redirecting…
                      </>
                    ) : (
                      <>
                        <Calendar className="w-4 h-4" />
                        Connect Google Calendar
                      </>
                    )}
                  </button>
                )}
              </div>
            </div>

            {/* Permissions footer */}
            <div className="px-6 py-3 border-t border-slate-100 bg-slate-50/50 text-[11px] font-semibold text-slate-500 flex flex-wrap items-center gap-x-4 gap-y-1">
              <span className="text-slate-400 uppercase tracking-wider text-[10px]">
                Permissions used
              </span>
              <span>· Read primary calendar events</span>
              <span>· Create &amp; update events you schedule here</span>
              <span>· Open Meet rooms for scheduled meetings so the agent can join</span>
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
}
