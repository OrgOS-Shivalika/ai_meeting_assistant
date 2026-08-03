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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageContainer, PageHeader } from "@/components/ui/page-header";

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
      <PageContainer width="default">
        <PageHeader
          eyebrow="Workspace"
          title="Integrations"
          description="Connect the tools your meetings already live in. Connect once; the agents use these signals when running meetings and automations."
        />

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <IntegrationCard
            name="Google Calendar"
            category="Calendar"
            description="Sync scheduled meetings to your Google Calendar and read upcoming meetings into the workspace."
            brandIcon={<Calendar />}
            brandColor="var(--vb-info)"
            state={googleState}
            errorMessage={googleError}
            connectedAs={googleEmail}
            busy={busy}
            onConnect={connectGoogle}
            onDisconnect={disconnectGoogle}
          />
        </section>

        {googleState === "connected" && <UpcomingGoogleEvents />}
      </PageContainer>
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
    <section className="mt-9">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="vb-label-caps">Google Calendar</p>
          <h2 className="vb-title-lg mt-1.5">Upcoming meetings</h2>
          <p className="mt-1.5 max-w-2xl text-[13px] text-muted-ink">
            Next {events.length || 10} events on your primary calendar. The bot
            auto-joins any meeting with a Google Meet link scheduled within the
            next 2 minutes.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          {loading ? (
            <Loader2 className="animate-spin" />
          ) : (
            <RefreshCw />
          )}
          Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-error/20 bg-error/8 px-4 py-3.5 text-[13px] font-medium text-error">
          {error}
        </div>
      )}

      {!error && !loading && events.length === 0 && (
        <EmptyState
          icon={Calendar}
          color="var(--vb-mint)"
          title="Nothing on the calendar"
          description="New events on your Google Calendar show up here."
          className="border-dashed"
        />
      )}

      {loading && events.length === 0 ? (
        <ul className="space-y-2.5">
          {[0, 1, 2].map((i) => (
            <li
              key={i}
              className="h-24 animate-pulse rounded-lg border border-hairline bg-surface-soft"
            />
          ))}
        </ul>
      ) : (
        <ul className="space-y-2.5">
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
    <li>
      <Card
        variant="default"
        className="flex flex-wrap items-start gap-5 rounded-lg p-5"
      >
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-2.5">
            <h3 className="vb-title-md max-w-xl truncate text-[17px]">
              {event.summary || "Untitled event"}
            </h3>
            {meetUrl && (
              <Badge variant="success">
                <Video className="size-2.5" />
                Meet
              </Badge>
            )}
          </div>

          <div className="mb-2.5 flex flex-wrap items-center gap-4 text-xs text-muted-ink">
            <span className="inline-flex items-center gap-1.5">
              <Clock className="size-3.5 text-muted-soft" />
              {whenText}
              {durationText && !isAllDay && (
                <span className="text-muted-soft"> · {durationText}</span>
              )}
            </span>
            {event.location && (
              <span className="inline-flex max-w-xs items-center gap-1.5 truncate">
                <MapPin className="size-3.5 text-muted-soft" />
                {event.location}
              </span>
            )}
            {(event.attendees?.length || 0) > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <Users className="size-3.5 text-muted-soft" />
                {event.attendees!.length} attendee
                {event.attendees!.length === 1 ? "" : "s"}
              </span>
            )}
          </div>

          {attendeesToShow.length > 0 && (
            <div className="mb-2.5 flex flex-wrap gap-2">
              {attendeesToShow.map((a, i) => (
                <span
                  key={i}
                  title={a.email}
                  className="inline-flex items-center gap-2 rounded-[10px] bg-surface-card px-3 py-1.5 text-[11px] font-medium text-body"
                >
                  {/* RSVP state, in the semantic hues. */}
                  <span
                    className="size-1.5 rounded-full"
                    style={{
                      background:
                        a.responseStatus === "accepted"
                          ? "var(--vb-success)"
                          : a.responseStatus === "declined"
                            ? "var(--vb-error)"
                            : a.responseStatus === "tentative"
                              ? "var(--vb-warning)"
                              : "var(--vb-muted-soft)",
                    }}
                  />
                  {a.displayName || a.email || "attendee"}
                </span>
              ))}
              {extraAttendees > 0 && (
                <span className="self-center text-[11px] text-muted-ink">
                  +{extraAttendees} more
                </span>
              )}
            </div>
          )}

          {event.description && (
            <p className="line-clamp-2 text-xs leading-relaxed text-muted-ink">
              {event.description.replace(/<[^>]*>/g, " ").trim()}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2.5">
          {meetUrl && (
            <Button size="sm" asChild>
              <a href={meetUrl} target="_blank" rel="noreferrer">
                <Video />
                Join
              </a>
            </Button>
          )}
          {event.htmlLink && (
            <a
              href={event.htmlLink}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-muted-ink hover:text-ink"
            >
              <ExternalLink className="size-3" />
              Open in Google
            </a>
          )}
        </div>
      </Card>
    </li>
  );
}
