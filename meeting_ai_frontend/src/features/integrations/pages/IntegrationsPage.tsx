import { useCallback, useEffect, useState } from "react";
import { Calendar  } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { apiClient } from "../../../services/apiClient";
import { authService } from "../../../services/authService";
import IntegrationCard, { type ConnectionState } from "../components/IntegrationCard";

/**
 * One-stop view of every external integration. Today only Google
 * Calendar is wired live (was the previous /agent-control page that
 * Phase 8E reclaimed for behavior controls). Future integrations slot
 * in as additional cards using the same shape — connect / disconnect /
 * status check.
 *
 * Design intent: this page should grow into the workspace's hub for
 * all third-party connections (Slack notifications, Salesforce sync,
 * HubSpot, Zoom, etc.). Each integration is a card with consistent
 * affordances.
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
          {/* Google Calendar — live */}
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

          {/* Future integrations — coming-soon placeholders */}
          {/* <IntegrationCard
            name="Slack"
            category="Notifications"
            description="Post meeting summaries + action items into Slack channels. Trigger automations from Slack messages."
            brandIcon={<Hash className="w-6 h-6 text-purple-600" />}
            state="disconnected"
            comingSoon
          />
          <IntegrationCard
            name="Salesforce"
            category="CRM"
            description="Sync extracted deal signals + objections from sales meetings into Salesforce Opportunities."
            brandIcon={<Briefcase className="w-6 h-6 text-sky-600" />}
            state="disconnected"
            comingSoon
          />
          <IntegrationCard
            name="HubSpot"
            category="CRM"
            description="Push meeting outcomes into HubSpot. Pull contact context before discovery calls."
            brandIcon={<Database className="w-6 h-6 text-orange-600" />}
            state="disconnected"
            comingSoon
          />
          <IntegrationCard
            name="Email digest"
            category="Notifications"
            description="Receive a daily digest of meeting summaries, decisions, and outstanding action items."
            brandIcon={<Mail className="w-6 h-6 text-rose-600" />}
            state="disconnected"
            comingSoon
          />
          <IntegrationCard
            name="Microsoft Teams"
            category="Calendar"
            description="Sync scheduled meetings + import transcripts from Teams calls."
            brandIcon={<MessageSquare className="w-6 h-6 text-blue-600" />}
            state="disconnected"
            comingSoon
          /> */}
        </section>
      </div>
    </Layout>
  );
}
