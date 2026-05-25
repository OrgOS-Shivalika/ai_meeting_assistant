import { CheckCircle2, ExternalLink, Loader2, Plug, Plug2 } from "lucide-react";

/**
 * Reusable card for one external integration (Google Calendar, CRM,
 * Slack, etc.). Same visual shell across providers — only the data +
 * actions vary. New integrations can be added by rendering this card
 * with the right state.
 */
export type ConnectionState = "loading" | "connected" | "disconnected" | "error";

export default function IntegrationCard({
  name,
  description,
  category,
  brandIcon,
  state,
  errorMessage,
  connectedAs,
  comingSoon = false,
  busy = false,
  onConnect,
  onDisconnect,
}: {
  name: string;
  description: string;
  category: string;
  brandIcon: React.ReactNode;
  state: ConnectionState;
  errorMessage?: string;
  connectedAs?: string;
  comingSoon?: boolean;
  busy?: boolean;
  onConnect?: () => void;
  onDisconnect?: () => void;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div className="w-12 h-12 rounded-xl bg-gray-50 border border-gray-100 flex items-center justify-center shrink-0">
          {brandIcon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <h3 className="font-semibold text-gray-900">{name}</h3>
            <StatusPill state={comingSoon ? "disconnected" : state} comingSoon={comingSoon} />
          </div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            {category}
          </p>
          <p className="text-sm text-gray-600 mt-2">{description}</p>
          {state === "connected" && connectedAs && (
            <p className="text-xs text-emerald-700 mt-2 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Connected as <span className="font-medium">{connectedAs}</span>
            </p>
          )}
          {state === "error" && errorMessage && (
            <p className="text-xs text-rose-700 mt-2">{errorMessage}</p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 mt-1">
        {comingSoon ? (
          <span className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-gray-100 text-gray-500">
            Coming soon
          </span>
        ) : state === "loading" ? (
          <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-500">
            <Loader2 className="w-3 h-3 animate-spin" /> Checking status…
          </span>
        ) : state === "connected" ? (
          <button
            onClick={onDisconnect}
            disabled={busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-rose-200 text-rose-700 hover:bg-rose-50 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Plug className="w-3 h-3" />
            )}
            Disconnect
          </button>
        ) : (
          <button
            onClick={onConnect}
            disabled={busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Plug2 className="w-3 h-3" />
            )}
            Connect
          </button>
        )}
        {state === "connected" && (
          <span className="inline-flex items-center gap-1 text-[11px] text-gray-400 ml-1">
            <ExternalLink className="w-3 h-3" />
            OAuth-secured
          </span>
        )}
      </div>
    </div>
  );
}


function StatusPill({
  state, comingSoon,
}: { state: ConnectionState; comingSoon: boolean }) {
  if (comingSoon) {
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-100 text-gray-500">
        Soon
      </span>
    );
  }
  if (state === "connected") {
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-700">
        Connected
      </span>
    );
  }
  if (state === "error") {
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-rose-100 text-rose-700">
        Error
      </span>
    );
  }
  if (state === "loading") {
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-100 text-gray-500">
        Checking
      </span>
    );
  }
  return (
    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-100 text-gray-600">
      Not connected
    </span>
  );
}
