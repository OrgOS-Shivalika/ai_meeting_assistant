import { useCallback, useEffect, useState } from "react";
import {
  Calendar,
  Clock,
  Users,
  Video,
  ExternalLink,
  RefreshCw,
  Loader2,
  MapPin,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { apiClient } from "../../../services/apiClient";
import { authService } from "../../../services/authService";
import IntegrationCard, { type ConnectionState } from "../components/IntegrationCard";

/**
 * One-stop view of every external integration. Today Google Calendar is
 * live; other cards land as they're wired.
 *
 * When Google is connected, this page also renders the next handful of
 * upcoming meetings pulled straight from the user's primary calendar
 * (via `GET /auth/google/events`). That gives the workspace visibility
 * into what the auto-join bot is watching, without leaving the page.
 */
export default function IntegrationsPage() {
  const [googleState, setGoogleState] = useState<ConnectionState>("loading");
  const [googleEmail, setGoogleEmail] = useState<string | undefined>();
  const [googleError, setGoogleError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  const refreshGoogle = useCallback(async () => {
    setGoogleState("loading");
    setGoogleError(undefined);
    try {
      const data = await apiClient("/auth/google/status");
      if (data?.is_connected) {
        setGoogleState("connected");
        setGoogleEmail(data?.google_info?.email);
      } else {
        setGoogleState("disconnected");
        setGoogleEmail(undefined);
      }
    } catch (e) {
      setGoogleState("error");
      setGoogleError((e as Error).message);
    }
  }, []);

  useEffect(() => { refreshGoogle(); }, [refreshGoogle]);

  const connectGoogle = async () => {
    setBusy(true);
    setGoogleError(undefined);
    try {
      const data = await authService.getGoogleAuthUrl();
      if (data?.auth_url) {
        window.location.href = data.auth_url;
        return;
      }
      setGoogleError("No auth URL returned by the server.");
    } catch (e) {
      setGoogleError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const disconnectGoogle = async () => {
    if (
      !window.confirm(
        "Disconnect Google Calendar? Scheduled meetings stop syncing " +
        "to your calendar until you reconnect."
      )
    ) return;
    setBusy(true);
    setGoogleError(undefined);
    try {
      await apiClient("/auth/google/disconnect", { method: "POST" });
      setGoogleState("disconnected");
      setGoogleEmail(undefined);
    } catch (e) {
      setGoogleError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout>
      <div className="px-8 py-8 max-w-6xl mx-auto">
        <header className="mb-6">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
            Integrations
          </p>
          <h1 className="text-2xl font-bold text-gray-900 mt-1">
            Connected services
          </h1>
          <p className="text-sm text-gray-500 mt-1 max-w-2xl">
            External services your workspace can talk to. Connect once;
            the AI uses these signals when running meetings + automations.
          </p>
        </header>

        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <IntegrationCard
            name="Google Calendar"
            category="Calendar"
            description="Sync scheduled meetings to your Google Calendar + read upcoming meetings into the workspace."
            brandIcon={<Calendar className="w-6 h-6 text-indigo-600" />}
            state={googleState}
            errorMessage={googleError}
            connectedAs={googleEmail}
            busy={busy}
            onConnect={connectGoogle}
            onDisconnect={disconnectGoogle}
          />
        </section>

        {googleState === "connected" && <UpcomingGoogleEvents />}
      </div>
    </Layout>
  );
}

// ─── Upcoming meetings ────────────────────────────────────────────────────────

type GoogleAttendee = {
  email?: string;
  displayName?: string;
  responseStatus?: string;
  self?: boolean;
};

type GoogleEvent = {
  id: string;
  summary?: string;
  description?: string;
  location?: string;
  htmlLink?: string;
  hangoutLink?: string;
  start?: { dateTime?: string; date?: string; timeZone?: string };
  end?: { dateTime?: string; date?: string; timeZone?: string };
  attendees?: GoogleAttendee[];
  organizer?: { email?: string; displayName?: string; self?: boolean };
  conferenceData?: {
    entryPoints?: { uri?: string; entryPointType?: string; label?: string }[];
  };
};

function UpcomingGoogleEvents() {
  const [events, setEvents] = useState<GoogleEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = (await apiClient("/auth/google/events")) as GoogleEvent[];
      setEvents(Array.isArray(data) ? data : []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <section className="mt-8">
      <div className="flex items-end justify-between mb-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
            Google Calendar
          </p>
          <h2 className="text-lg font-semibold text-gray-900 mt-1">
            Upcoming meetings
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Next {events.length || 10} events on your primary calendar. The bot
            auto-joins any meeting with a Google Meet link scheduled within
            the next 2 minutes.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCw className="w-3 h-3" />
          )}
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {!error && !loading && events.length === 0 && (
        <div className="rounded-lg border border-dashed border-gray-200 px-6 py-10 text-center">
          <Calendar className="w-6 h-6 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No upcoming meetings.</p>
          <p className="text-xs text-gray-400 mt-1">
            New events on your Google Calendar will show up here.
          </p>
        </div>
      )}

      {loading && events.length === 0 ? (
        <ul className="space-y-2">
          {[0, 1, 2].map((i) => (
            <li
              key={i}
              className="h-24 rounded-xl border border-gray-200 bg-gray-50 animate-pulse"
            />
          ))}
        </ul>
      ) : (
        <ul className="space-y-2">
          {events.map((event) => (
            <EventRow key={event.id} event={event} />
          ))}
        </ul>
      )}
    </section>
  );
}

function EventRow({ event }: { event: GoogleEvent }) {
  const startISO = event.start?.dateTime || event.start?.date || null;
  const endISO = event.end?.dateTime || event.end?.date || null;

  const startDate = startISO ? new Date(startISO) : null;
  const endDate = endISO ? new Date(endISO) : null;
  const isAllDay = !event.start?.dateTime && !!event.start?.date;

  const meetUrl =
    event.hangoutLink ||
    event.conferenceData?.entryPoints?.find((e) => e.entryPointType === "video")?.uri ||
    null;

  const attendeesToShow = (event.attendees || []).slice(0, 4);
  const extraAttendees = Math.max(0, (event.attendees?.length || 0) - attendeesToShow.length);

  const durationText = (() => {
    if (!startDate || !endDate) return null;
    if (isAllDay) return "All day";
    const mins = Math.round((endDate.getTime() - startDate.getTime()) / 60000);
    if (mins < 60) return `${mins} min`;
    const hrs = Math.floor(mins / 60);
    const rem = mins % 60;
    return rem === 0 ? `${hrs}h` : `${hrs}h ${rem}m`;
  })();

  const whenText = (() => {
    if (!startDate) return "—";
    const now = new Date();
    const sameDay = startDate.toDateString() === now.toDateString();
    const dateStr = startDate.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    if (isAllDay) return `${dateStr} · all day`;
    const timeStr = startDate.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
    return sameDay ? `Today · ${timeStr}` : `${dateStr} · ${timeStr}`;
  })();

  return (
    <li className="rounded-xl border border-gray-200 bg-white p-4 flex flex-wrap items-start gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          <h3 className="font-semibold text-gray-900 truncate max-w-xl">
            {event.summary || "Untitled event"}
          </h3>
          {meetUrl && (
            <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded">
              <Video className="w-2.5 h-2.5" />
              Meet
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 flex-wrap text-xs text-gray-500 mb-2">
          <span className="inline-flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-gray-400" />
            {whenText}
            {durationText && !isAllDay && (
              <span className="text-gray-400"> · {durationText}</span>
            )}
          </span>
          {event.location && (
            <span className="inline-flex items-center gap-1.5 truncate max-w-xs">
              <MapPin className="w-3.5 h-3.5 text-gray-400" />
              {event.location}
            </span>
          )}
          {(event.attendees?.length || 0) > 0 && (
            <span className="inline-flex items-center gap-1.5">
              <Users className="w-3.5 h-3.5 text-gray-400" />
              {event.attendees!.length} attendee
              {event.attendees!.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {attendeesToShow.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {attendeesToShow.map((a, i) => (
              <span
                key={i}
                title={a.email}
                className="inline-flex items-center gap-1 text-[11px] bg-gray-50 border border-gray-200 rounded-full px-2 py-0.5 text-gray-700"
              >
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{
                    background:
                      a.responseStatus === "accepted"
                        ? "#22c55e"
                        : a.responseStatus === "declined"
                          ? "#ef4444"
                          : a.responseStatus === "tentative"
                            ? "#f59e0b"
                            : "#9ca3af",
                  }}
                />
                {a.displayName || a.email || "attendee"}
              </span>
            ))}
            {extraAttendees > 0 && (
              <span className="text-[11px] text-gray-500 self-center">
                +{extraAttendees} more
              </span>
            )}
          </div>
        )}

        {event.description && (
          <p className="text-xs text-gray-600 line-clamp-2 leading-relaxed">
            {event.description.replace(/<[^>]*>/g, " ").trim()}
          </p>
        )}
      </div>

      <div className="flex flex-col items-end gap-2 shrink-0">
        {meetUrl && (
          <a
            href={meetUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700"
          >
            <Video className="w-3 h-3" />
            Join
          </a>
        )}
        {event.htmlLink && (
          <a
            href={event.htmlLink}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-700"
          >
            <ExternalLink className="w-3 h-3" />
            Open in Google
          </a>
        )}
      </div>
    </li>
  );
}
