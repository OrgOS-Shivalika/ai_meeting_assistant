import { useEffect, useState } from "react";
import { apiClient } from "../../../services/apiClient";
import Layout from "../../../shared/components/Layout";
import {
  Calendar,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Video,
  Clock,
  ExternalLink,
  LogOut,
  Users,
} from "lucide-react";
import { authService } from "../../../services/authService";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { IconChip } from "@/components/ui/icon-chip";
import { EmptyState } from "@/components/ui/empty-state";
import { PageContainer } from "@/components/ui/page-header";
import { initials } from "@/lib/vibrant";
import { cn } from "@/lib/utils";

export default function CalendarPage() {
  const [isConnected, setIsConnected] = useState<boolean | null>(null);
  const [googleInfo, setGoogleInfo] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [error, setError] = useState("");

  const fetchData = async () => {
    setIsLoading(true);
    setError("");
    try {
      const status = await apiClient("/auth/google/status");
      setIsConnected(status.is_connected);
      setGoogleInfo(status.google_info);

      if (status.is_connected) {
        const eventsData = await apiClient("/auth/google/events");
        setEvents(eventsData);
      }
    } catch (err) {
      console.error("Failed to fetch calendar data", err);
      setError("Failed to load calendar events. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleConnect = async () => {
    try {
      const data = await authService.getGoogleAuthUrl();
      if (data.auth_url) {
        window.location.href = data.auth_url;
      }
    } catch (err) {
      console.error("Failed to get Google Auth URL", err);
      setError("Failed to initiate Google connection.");
    }
  };

  const handleDisconnect = async () => {
    if (!window.confirm("Are you sure you want to disconnect your Google Calendar?"))
      return;

    setIsDisconnecting(true);
    setError("");
    try {
      await apiClient("/auth/google/disconnect", { method: "POST" });
      setIsConnected(false);
      setGoogleInfo(null);
      setEvents([]);
    } catch (err) {
      console.error("Failed to disconnect Google Calendar", err);
      setError("Failed to disconnect Google Calendar. Please try again.");
    } finally {
      setIsDisconnecting(false);
    }
  };

  const formatTime = (isoString: string) =>
    new Date(isoString).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });

  const formatDate = (isoString: string) =>
    new Date(isoString).toLocaleDateString([], {
      weekday: "short",
      month: "short",
      day: "numeric",
    });

  return (
    <Layout>
      <PageContainer width="narrow">
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <IconChip size="xl" color="var(--vb-info)">
              <Calendar />
            </IconChip>
            <div>
              <h1 className="vb-display-sm text-[30px]">Google Calendar</h1>
              <p className="mt-1 text-sm text-muted-ink">
                Sync and automate your meetings.
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={fetchData} disabled={isLoading}>
            <RefreshCw className={cn(isLoading && "animate-spin")} />
            Sync now
          </Button>
        </div>

        {error && (
          <div className="mb-6 flex items-center gap-3 rounded-lg border border-error/20 bg-error/8 px-4 py-3.5">
            <AlertCircle className="size-4 shrink-0 text-error" />
            <p className="text-[13px] font-medium text-error">{error}</p>
          </div>
        )}

        {isLoading && !events.length ? (
          <div className="flex flex-col items-center justify-center gap-4 py-32">
            <span
              className="size-10 animate-spin rounded-full border-[3px]"
              style={{
                borderColor: "color-mix(in srgb, var(--vb-info) 25%, white)",
                borderTopColor: "var(--vb-info)",
              }}
            />
            <p className="text-sm text-muted-ink">Loading your calendar…</p>
          </div>
        ) : !isConnected ? (
          <EmptyState
            icon={Calendar}
            color="var(--vb-info)"
            title="Connect your calendar"
            description="Link Google Calendar and the bot joins your meetings, captures the transcript and routes the follow-ups."
            className="mx-auto max-w-2xl rounded-2xl py-16"
            action={<Button onClick={handleConnect}>Connect Google Calendar</Button>}
          />
        ) : (
          <div className="flex flex-col gap-6">
            {/* Connection card */}
            <Card
              variant="default"
              className="flex flex-col items-center justify-between gap-6 rounded-2xl p-7 md:flex-row"
            >
              <div className="flex flex-col items-center gap-5 md:flex-row">
                {googleInfo?.picture ? (
                  <img
                    src={googleInfo.picture}
                    alt="Profile"
                    className="size-16 rounded-[18px] object-cover"
                  />
                ) : (
                  <Avatar
                    size="xl"
                    name={googleInfo?.name || googleInfo?.email || "User"}
                    color="var(--vb-pink)"
                  />
                )}
                <div className="text-center md:text-left">
                  <h2 className="vb-title-lg text-[22px]">
                    {googleInfo?.name || "Google user"}
                  </h2>
                  <p className="mt-0.5 mb-2 text-sm text-muted-ink">
                    {googleInfo?.email}
                  </p>
                  <Badge variant="success" size="lg">
                    <CheckCircle2 className="size-3.5" />
                    Connected
                  </Badge>
                </div>
              </div>
              <Button
                variant="destructiveOutline"
                size="sm"
                onClick={handleDisconnect}
                disabled={isDisconnecting}
              >
                <LogOut />
                {isDisconnecting ? "Disconnecting…" : "Disconnect"}
              </Button>
            </Card>

            {/* Upcoming meetings */}
            <Card variant="default" className="overflow-hidden rounded-2xl">
              <div className="flex items-center justify-between border-b border-hairline-soft px-7 py-6">
                <h3 className="vb-title-md">Upcoming meetings</h3>
                <Badge variant="secondary" size="lg">
                  {events.length} {events.length === 1 ? "event" : "events"}
                </Badge>
              </div>
              <div>
                {events.length > 0 ? (
                  events.map((event) => (
                    <div
                      key={event.id}
                      className="border-b border-hairline-soft px-7 py-6 transition-colors last:border-0 hover:bg-surface-soft/50"
                    >
                      <div className="flex items-start justify-between gap-5">
                        <div className="flex-1">
                          <h4 className="vb-title-md text-[17px]">
                            {event.summary || "Untitled meeting"}
                          </h4>
                          <div className="mt-2 flex flex-wrap items-center gap-4 text-[13px] text-muted-ink">
                            <span className="inline-flex items-center gap-1.5">
                              <Calendar className="size-3.5 text-muted-soft" />
                              {formatDate(event.start.dateTime || event.start.date)}
                            </span>
                            <span className="inline-flex items-center gap-1.5">
                              <Clock className="size-3.5 text-muted-soft" />
                              {formatTime(event.start.dateTime || event.start.date)}
                            </span>
                            {event.hangoutLink && (
                              <a
                                href={event.hangoutLink}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1.5 font-semibold text-info hover:underline"
                              >
                                <Video className="size-3.5" />
                                Google Meet
                              </a>
                            )}
                          </div>
                        </div>
                        {event.htmlLink && (
                          <a
                            href={event.htmlLink}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex size-[38px] shrink-0 items-center justify-center rounded-md border border-hairline text-muted-soft transition-colors hover:border-ink hover:text-ink"
                            title="View in Google Calendar"
                          >
                            <ExternalLink className="size-4" />
                          </a>
                        )}
                      </div>

                      {event.attendees && event.attendees.length > 0 && (
                        <div className="mt-4 border-t border-hairline-soft pt-4">
                          <div className="mb-2.5 flex items-center gap-1.5">
                            <Users className="size-3.5 text-muted-soft" />
                            <span className="vb-label-caps">Participants</span>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {event.attendees.map((attendee: any, idx: number) => (
                              <span
                                key={idx}
                                className="inline-flex items-center gap-2 rounded-[10px] bg-surface-card px-3 py-1.5 text-xs font-medium text-body"
                                title={attendee.email}
                              >
                                <span className="inline-flex size-5 items-center justify-center rounded-xs border border-hairline bg-canvas text-[9px] font-semibold text-muted-ink">
                                  {initials(
                                    attendee.displayName || attendee.email,
                                  ).slice(0, 1)}
                                </span>
                                {attendee.displayName || attendee.email}
                                {attendee.organizer && (
                                  <Badge variant="info" size="sm">
                                    Host
                                  </Badge>
                                )}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <EmptyState
                    bare
                    icon={Calendar}
                    color="var(--vb-mint)"
                    title="Nothing on the calendar"
                    description="Your next few days are clear."
                  />
                )}
              </div>
            </Card>
          </div>
        )}
      </PageContainer>
    </Layout>
  );
}
