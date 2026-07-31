import { CheckCircle2, Loader2, Plug, Plug2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IconChip } from "@/components/ui/icon-chip";

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
  brandColor = "var(--vb-info)",
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
  /** Brand hue for the icon chip — cycle it across the grid. */
  brandColor?: string;
  state: ConnectionState;
  errorMessage?: string;
  connectedAs?: string;
  comingSoon?: boolean;
  busy?: boolean;
  onConnect?: () => void;
  onDisconnect?: () => void;
}) {
  return (
    <Card variant="default" className="flex flex-col gap-4 rounded-xl p-[22px]">
      <div className="flex items-start justify-between gap-3">
        <IconChip size="lg" color={brandColor} className="size-[46px] rounded-[13px]">
          {brandIcon}
        </IconChip>
        {state === "connected" && !comingSoon ? (
          <Badge variant="success" dot>
            Connected
          </Badge>
        ) : (
          <StatusPill state={state} comingSoon={comingSoon} />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <h3 className="vb-title-md text-[17px]">{name}</h3>
        <p className="vb-label-caps mt-1">{category}</p>
        <p className="mt-2.5 text-[13px] leading-relaxed text-muted-ink">
          {description}
        </p>
        {state === "connected" && connectedAs && (
          <p className="mt-2.5 flex items-center gap-1.5 text-xs text-success">
            <CheckCircle2 className="size-3.5" />
            Connected as <span className="font-medium">{connectedAs}</span>
          </p>
        )}
        {state === "error" && errorMessage && (
          <p className="mt-2.5 text-xs text-error">{errorMessage}</p>
        )}
      </div>

      <div className="flex items-center gap-2.5">
        {comingSoon ? (
          <Button variant="secondary" size="sm" disabled>
            Coming soon
          </Button>
        ) : state === "loading" ? (
          <span className="inline-flex items-center gap-2 text-xs text-muted-ink">
            <Loader2 className="size-3.5 animate-spin" /> Checking status…
          </span>
        ) : state === "connected" ? (
          <Button
            variant="destructiveOutline"
            size="sm"
            onClick={onDisconnect}
            disabled={busy}
          >
            {busy ? <Loader2 className="animate-spin" /> : <Plug />}
            Disconnect
          </Button>
        ) : (
          <Button size="sm" onClick={onConnect} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Plug2 />}
            Connect
          </Button>
        )}
        {state === "connected" && (
          <span className="font-mono text-[11px] text-muted-soft">
            OAuth-secured
          </span>
        )}
      </div>
    </Card>
  );
}

function StatusPill({
  state,
  comingSoon,
}: {
  state: ConnectionState;
  comingSoon: boolean;
}) {
  if (comingSoon) return <Badge variant="secondary">Soon</Badge>;
  if (state === "error") return <Badge variant="error">Error</Badge>;
  if (state === "loading") return <Badge variant="secondary">Checking</Badge>;
  return <Badge variant="outline">Not connected</Badge>;
}
