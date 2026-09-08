import { useEffect, useState } from "react";
import {
  User,
  Building2,
  Sparkles,
  Zap,
  Bell,
  Shield,
  CreditCard,
  Trash2,
  Check,
  ChevronRight,
  MessageSquare,
  Calendar,
  Ticket,
  Cloud,
  Radio,
  ExternalLink,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  applyBackground,
  applyBackgroundImage,
  BACKGROUNDS,
  clearBackgroundImage,
  fileToBackgroundDataUrl,
  getBackgroundId,
  getBackgroundImage,
  setBackground,
  setBackgroundImage,
} from "../../../shared/background";
import {
  fetchNotificationPrefs,
  updateNotificationPrefs,
  type NotificationPrefs,
} from "@/features/kanban/api";
import { getTheme, setTheme, type Theme } from "../../../shared/theme";
import { Input } from "@/components/ui/input";
import { Field as UiField } from "@/components/ui/label";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { Select as UiSelect } from "@/components/ui/select";
import { SettingRow, Switch } from "@/components/ui/switch";
import { useCurrentUser } from "../../auth/hooks/useCurrentUser";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Small inline primitives — kept in-file since only settings uses them.
// ---------------------------------------------------------------------------
/** Thin wrapper so the section bodies keep their `onChange` signature. */
function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <Switch checked={checked} onCheckedChange={onChange} disabled={disabled} />
  );
}

function Row({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <SettingRow title={title} description={description} control={children} />
  );
}

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <UiField label={label} hint={hint}>
      {children}
    </UiField>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-5">
        <h2 className="vb-title-lg">{title}</h2>
        <p className="mt-1.5 text-sm text-muted-ink">{description}</p>
      </header>
      <Card variant="default" className="rounded-lg px-[26px] py-2">
        {children}
      </Card>
    </section>
  );
}

/** Local `Select` keeps the `options` prop the section bodies already pass. */
function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <UiSelect
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-10 w-auto min-w-40"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </UiSelect>
  );
}

// ---------------------------------------------------------------------------
// Section catalog
// ---------------------------------------------------------------------------
const SECTIONS = [
  { id: "profile", label: "Profile", icon: User },
  { id: "workspace", label: "Workspace", icon: Building2 },
  { id: "ai", label: "AI & Automation", icon: Sparkles },
  { id: "integrations", label: "Integrations", icon: Zap },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "security", label: "Security", icon: Shield },
  { id: "billing", label: "Billing", icon: CreditCard },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function SettingsPage() {
  const [active, setActive] = useState<SectionId>("profile");

  return (
    <Layout>
      <PageContainer width="default">
        <PageHeader
          eyebrow="Workspace"
          title="Settings"
          description="Manage your profile, workspace, agent defaults and integrations."
        />

        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[220px_1fr]">
          {/* Section nav — same active treatment as the app sidebar. */}
          <nav className="flex flex-row gap-0.5 self-start overflow-x-auto lg:sticky lg:top-6 lg:flex-col">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActive(id)}
                className={cn(
                  "group flex h-[38px] w-full shrink-0 items-center gap-[11px] rounded-[10px] px-3 text-[13.5px] transition-colors",
                  active === id
                    ? "bg-surface-card font-semibold text-ink"
                    : "font-medium text-muted-ink hover:bg-surface-soft hover:text-ink",
                )}
              >
                <Icon
                  className={cn(
                    "size-[17px] shrink-0",
                    active === id ? "text-ink" : "text-muted-soft",
                  )}
                />
                <span className="flex-1 text-left whitespace-nowrap">
                  {label}
                </span>
                {active === id && (
                  <ChevronRight className="hidden size-3.5 text-muted-soft lg:block" />
                )}
              </button>
            ))}
          </nav>

          {/* Section content */}
          <div className="min-w-0">
            {active === "profile" && <ProfileSection />}
            {active === "workspace" && <WorkspaceSection />}
            {active === "ai" && <AISection />}
            {active === "integrations" && <IntegrationsSection />}
            {active === "notifications" && <NotificationsSection />}
            {active === "security" && <SecuritySection />}
            {active === "billing" && <BillingSection />}
          </div>
        </div>
      </PageContainer>
    </Layout>
  );
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------
/** Personal page background. Local to this browser and to this person — see
 *  `shared/background.ts` for why it is not stored server-side. */
/** Which events send you EMAIL.
 *
 *  In-app notifications are not listed because they are not optional: the bell
 *  costs the reader nothing and can be ignored, while email interrupts. Only
 *  the interrupting half is opt-out, so turning email off still leaves a
 *  complete feed for anyone who later turns it back on.
 */
function NotificationPrefs() {
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchNotificationPrefs()
      .then((p) => alive && setPrefs(p))
      .catch(() => alive && setError("Couldn't load your notification settings."));
    return () => {
      alive = false;
    };
  }, []);

  const toggle = async (kind: keyof NotificationPrefs) => {
    if (!prefs) return;
    const next = { ...prefs, [kind]: !prefs[kind] };
    setPrefs(next); // optimistic — a toggle that lags feels broken
    try {
      setPrefs(await updateNotificationPrefs({ [kind]: next[kind] }));
    } catch {
      setPrefs(prefs); // put it back; the server is the source of truth
      setError("Couldn't save that. Try again.");
    }
  };

  const ROWS: [keyof NotificationPrefs, string, string][] = [
    ["task_assigned", "Assigned to me", "When someone gives you a task."],
    ["task_mentioned", "Mentions", "When someone @mentions you in a comment."],
    ["task_due_soon", "Due soon", "The day before a task assigned to you is due."],
  ];

  return (
    <div className="border-t border-hairline py-5">
      <p className="vb-title-sm">Email notifications</p>
      <p className="mt-0.5 mb-3 text-[12px] text-muted-ink">
        The bell in the sidebar always shows these. This only controls whether
        they also reach your inbox.
      </p>
      {error && <p className="mb-2 text-[11px] font-medium text-error">{error}</p>}
      <div className="flex flex-col gap-2">
        {ROWS.map(([kind, label, hint]) => (
          <label
            key={kind}
            className="flex cursor-pointer items-start gap-2.5 text-[12px]"
          >
            <input
              type="checkbox"
              className="mt-0.5"
              checked={prefs ? prefs[kind] : true}
              disabled={!prefs}
              onChange={() => void toggle(kind)}
            />
            <span>
              <span className="font-medium text-ink">{label}</span>
              <span className="block text-[11px] text-muted-ink">{hint}</span>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

/** Light / dark. Applies on click and persists itself. */
function ThemePicker() {
  const [theme, setThemeState] = useState<Theme>(getTheme);

  const choose = (next: Theme) => {
    setThemeState(next);
    setTheme(next);
    // Re-run the background so a light colour preset is dropped on the way
    // into dark and restored on the way out.
    applyBackground(getBackgroundId());
    applyBackgroundImage(getBackgroundImage());
  };

  return (
    <div className="border-t border-hairline py-5">
      <p className="vb-title-sm">Appearance</p>
      <p className="mt-0.5 mb-3 text-[12px] text-muted-ink">
        Only you see this. Light unless you pick dark.
      </p>
      <div className="flex gap-2">
        {(["light", "dark"] as Theme[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => choose(t)}
            aria-pressed={theme === t}
            className={`rounded-md border px-3 py-1.5 text-[11px] font-medium capitalize transition-all ${
              theme === t
                ? "border-ink ring-1 ring-ink"
                : "border-hairline hover:border-muted-soft"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
    </div>
  );
}

function BackgroundPicker() {
  const [selected, setSelected] = useState(getBackgroundId);
  const [image, setImage] = useState<string | null>(getBackgroundImage);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const choose = (id: string) => {
    setSelected(id);
    // Applies immediately: a preview that needs a save button to take effect
    // makes people guess what they are choosing.
    setBackground(id);
    // A colour is a different answer to the same question, so picking one
    // drops the image rather than leaving it on top where the colour would
    // appear to do nothing.
    if (image) {
      clearBackgroundImage();
      setImage(null);
    }
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const dataUrl = await fileToBackgroundDataUrl(file);
      setBackgroundImage(dataUrl);
      setImage(dataUrl);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't use that image.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-hairline py-5">
      <p className="vb-title-sm">Background</p>
      <p className="mt-0.5 mb-3 text-[12px] text-muted-ink">
        Only you see this — a colour, or an image of your own. Saved in this
        browser, so it won't follow you to another device.
      </p>
      <div className="flex flex-wrap gap-2">
        {BACKGROUNDS.map((b) => (
          <button
            key={b.id}
            type="button"
            onClick={() => choose(b.id)}
            aria-pressed={selected === b.id}
            title={b.label}
            className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-all ${
              selected === b.id
                ? "border-ink ring-1 ring-ink"
                : "border-hairline hover:border-muted-soft"
            }`}
          >
            <span
              className="size-4 rounded-full border border-hairline"
              style={{ backgroundColor: b.value }}
            />
            {b.label}
          </button>
        ))}

        {/* Upload tile, same shape as the colour tiles so the two read as one
            set of choices rather than two features. */}
        <label
          className={`flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-all ${
            image ? "border-ink ring-1 ring-ink" : "border-hairline hover:border-muted-soft"
          } ${busy ? "opacity-50" : ""}`}
          title="Use your own image"
        >
          <span
            className="size-4 overflow-hidden rounded-full border border-hairline bg-surface-soft bg-cover bg-center"
            style={image ? { backgroundImage: `url("${image}")` } : undefined}
          />
          {busy ? "Processing…" : image ? "Your image" : "Upload image"}
          <input
            type="file"
            accept="image/*"
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              void upload(e.target.files?.[0]);
              // Reset so re-picking the SAME file fires onChange again.
              e.target.value = "";
            }}
          />
        </label>

        {image && (
          <button
            type="button"
            onClick={() => {
              clearBackgroundImage();
              setImage(null);
              setError(null);
            }}
            className="rounded-md border border-hairline px-2.5 py-1.5 text-[11px] font-medium text-muted-ink hover:border-muted-soft"
          >
            Remove image
          </button>
        )}
      </div>

      {error && (
        <p className="mt-2 text-[11px] font-medium text-error">{error}</p>
      )}
    </div>
  );
}

function ProfileSection() {
  const { user } = useCurrentUser();
  const [name, setName] = useState(user?.name || "");
  const [tz, setTz] = useState("America/New_York");

  const initials =
    user?.name
      ?.split(/\s+/)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase() || "")
      .join("") || "?";

  return (
    <Section
      title="Profile"
      description="How you appear across meetings and your workspace."
    >
      <div className="flex items-center gap-[18px] py-5">
        {/* Rounded-square avatar in brand pink — the DS never uses a
            cool gradient for identity. */}
        {user?.google_profile_picture ? (
          <img
            src={user.google_profile_picture}
            alt={user.name}
            className="size-16 rounded-[18px] object-cover"
          />
        ) : (
          <span className="inline-flex size-16 items-center justify-center rounded-[18px] bg-pink font-display text-2xl font-semibold text-white">
            {initials}
          </span>
        )}
        <div className="flex-1">
          <div className="flex gap-2">
            <Button variant="outline" size="sm">
              Change photo
            </Button>
            <Button variant="ghost" size="sm">
              Remove
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-muted-ink">
            PNG or JPG, up to 2 MB.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 border-t border-hairline-soft py-5 sm:grid-cols-2">
        <Field label="Full name">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-10"
          />
        </Field>
        <Field label="Email" hint="Contact support to change your email.">
          <Input
            value={user?.email || ""}
            readOnly
            className="h-10 bg-surface-soft"
          />
        </Field>
        <Field label="Timezone">
          <Select
            value={tz}
            onChange={setTz}
            options={[
              { value: "America/New_York", label: "America / New York" },
              { value: "America/Los_Angeles", label: "America / Los Angeles" },
              { value: "Europe/London", label: "Europe / London" },
              { value: "Asia/Kolkata", label: "Asia / Kolkata" },
              { value: "Asia/Tokyo", label: "Asia / Tokyo" },
            ]}
          />
        </Field>
        <Field label="Role">
          <div className="flex h-10 items-center">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-lavender/22 px-[9px] py-1 text-[11px] font-semibold text-purple-700">
              Org Admin
            </span>
          </div>
        </Field>
      </div>

      {/* Applies on click and persists itself, so it sits ABOVE the
          Cancel/Save bar — those buttons belong to the profile fields and do
          not govern it. */}
      <NotificationPrefs />
      <ThemePicker />
      <BackgroundPicker />

      <div className="-mx-[26px] mt-2 flex items-center justify-end gap-2.5 border-t border-hairline-soft bg-surface-soft px-[26px] py-4">
        <Button variant="ghost" size="sm">
          Cancel
        </Button>
        <Button size="sm">Save changes</Button>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------
function WorkspaceSection() {
  const { user } = useCurrentUser();
  const [orgName, setOrgName] = useState(
    user?.organization?.name || "Acme, Inc.",
  );
  const [region, setRegion] = useState("us-east-1");
  const [lang, setLang] = useState("auto");

  return (
    <>
      <Section
        title="Workspace"
        description="Details that apply to everyone in your organization."
      >
        <div className="grid grid-cols-1 gap-4 border-t border-hairline-soft py-5 sm:grid-cols-2">
          <Field label="Workspace name">
            <Input
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              className="h-10"
            />
          </Field>
          <Field label="Slug" hint="Used in shared meeting links.">
            <Input value="acme" readOnly className="h-10 bg-surface-soft" />
          </Field>
          <Field label="Region" hint="Where meeting data is stored.">
            <Select
              value={region}
              onChange={setRegion}
              options={[
                { value: "us-east-1", label: "US East (N. Virginia)" },
                { value: "eu-west-1", label: "EU West (Ireland)" },
                { value: "ap-northeast-1", label: "Asia Pacific (Tokyo)" },
              ]}
            />
          </Field>
          <Field label="Default meeting language">
            <Select
              value={lang}
              onChange={setLang}
              options={[
                { value: "auto", label: "Auto-detect" },
                { value: "en", label: "English" },
                { value: "es", label: "Spanish" },
                { value: "fr", label: "French" },
                { value: "de", label: "German" },
                { value: "hi", label: "Hindi" },
                { value: "ja", label: "Japanese" },
              ]}
            />
          </Field>
        </div>
        <div className="-mx-[26px] mt-2 flex items-center justify-end gap-2.5 border-t border-hairline-soft bg-surface-soft px-[26px] py-4">
          <Button variant="ghost" size="sm">
            Cancel
          </Button>
          <Button size="sm">Save changes</Button>
        </div>
      </Section>

      <section className="mt-8">
        <header className="mb-5">
          <h2 className="vb-title-lg">
            Danger zone
          </h2>
          <p className="text-sm text-muted-ink mt-1">
            Irreversible actions. Proceed with care.
          </p>
        </header>
        <div className="rounded-lg border border-red-200 bg-red-50/40 p-5 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-ink">
              Delete this workspace
            </div>
            <p className="text-xs text-muted-ink mt-1">
              This permanently removes all meetings, transcripts, and members.
            </p>
          </div>
          <Button variant="destructive" size="sm">
            <Trash2 className="w-3.5 h-3.5" />
            Delete workspace
          </Button>
        </div>
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------
// AI & Automation
// ---------------------------------------------------------------------------
function AISection() {
  const [defaultAgent, setDefaultAgent] = useState("meeting-scrum");
  const [provider, setProvider] = useState<"deepgram" | "assemblyai">(
    "deepgram",
  );
  const [autoSummary, setAutoSummary] = useState(true);
  const [autoTasks, setAutoTasks] = useState(true);
  const [autoDecisions, setAutoDecisions] = useState(true);
  const [briefingSpoken, setBriefingSpoken] = useState(false);
  const [liveCopilot, setLiveCopilot] = useState(true);
  const [redactPII, setRedactPII] = useState(true);

  return (
    <Section
      title="AI & Automation"
      description="Tune what OrgOS extracts and how it behaves during a call."
    >
      <div className="grid grid-cols-1 gap-4 border-t border-hairline-soft py-5 sm:grid-cols-2">
        <Field label="Default agent">
          <Select
            value={defaultAgent}
            onChange={setDefaultAgent}
            options={[
              { value: "meeting-scrum", label: "Meeting & Scrum" },
              { value: "engineering", label: "Engineering" },
              { value: "product", label: "Product" },
              { value: "executive", label: "Executive" },
              { value: "incident", label: "Incident Response" },
              { value: "compliance", label: "Compliance" },
            ]}
          />
        </Field>
        <Field label="Transcription provider">
          <Select
            value={provider}
            onChange={(v) => setProvider(v as "deepgram" | "assemblyai")}
            options={[
              { value: "deepgram", label: "Deepgram (Nova-3)" },
              { value: "assemblyai", label: "AssemblyAI" },
            ]}
          />
        </Field>
      </div>

      <div className="px-5">
        <Row
          title="Auto-generate summary"
          description="Produce a summary and key takeaways when a meeting ends."
        >
          <Toggle checked={autoSummary} onChange={setAutoSummary} />
        </Row>
        <Row
          title="Extract action items"
          description="Detect tasks and assign owners automatically."
        >
          <Toggle checked={autoTasks} onChange={setAutoTasks} />
        </Row>
        <Row
          title="Extract decisions"
          description="Capture explicit decisions with context."
        >
          <Toggle checked={autoDecisions} onChange={setAutoDecisions} />
        </Row>
        <Row
          title="Speak closing briefing in-call"
          description="Bot recaps the meeting out loud in the last 30 seconds."
        >
          <Toggle checked={briefingSpoken} onChange={setBriefingSpoken} />
        </Row>
        <Row
          title="Live copilot suggestions"
          description="Surface prompts and follow-ups while the meeting runs."
        >
          <Toggle checked={liveCopilot} onChange={setLiveCopilot} />
        </Row>
        <Row
          title="Redact PII"
          description="Mask emails, phone numbers, and SSNs before storage."
        >
          <Toggle checked={redactPII} onChange={setRedactPII} />
        </Row>
      </div>

      <div className="-mx-[26px] mt-2 flex items-center justify-end gap-2.5 border-t border-hairline-soft bg-surface-soft px-[26px] py-4">
        <Button size="sm">Save preferences</Button>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Integrations
// ---------------------------------------------------------------------------
const INTEGRATIONS = [
  {
    id: "google",
    name: "Google Calendar",
    description: "Sync events, attendees, and dispatch the bot from invites.",
    icon: Calendar,
    connected: true,
  },
  {
    id: "recall",
    name: "Recall.ai",
    description: "Meeting bot for Google Meet, Zoom, Teams, and Webex.",
    icon: Radio,
    connected: true,
    locked: true,
  },
  {
    id: "slack",
    name: "Slack",
    description: "Post summaries and route action items to channels.",
    icon: MessageSquare,
    connected: false,
  },
  {
    id: "jira",
    name: "Jira",
    description: "Create tickets from extracted action items.",
    icon: Ticket,
    connected: false,
  },
  {
    id: "salesforce",
    name: "Salesforce",
    description: "Log call notes and next steps against opportunities.",
    icon: Cloud,
    connected: false,
  },
];

function IntegrationsSection() {
  return (
    <Section
      title="Integrations"
      description="Connect OrgOS to the tools your team already uses."
    >
      {INTEGRATIONS.map(({ id, name, description, icon: Icon, connected, locked }) => (
        <div key={id} className="p-5 flex items-center gap-4">
          <div className="inline-flex size-10 shrink-0 items-center justify-center rounded-md bg-surface-card">
            <Icon className="size-5 text-body-strong" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-ink">{name}</h3>
              {connected && (
                <span className="inline-flex items-center gap-1 rounded-full bg-success/12 px-2 py-0.5 text-[10px] font-semibold text-success">
                  <Check className="w-2.5 h-2.5" strokeWidth={3} />
                  Connected
                </span>
              )}
            </div>
            <p className="text-xs text-muted-ink mt-0.5">{description}</p>
          </div>
          <div className="shrink-0">
            {locked ? (
              <span className="text-[11px] text-muted-soft">System</span>
            ) : connected ? (
              <Button variant="outline" size="sm">
                Manage
              </Button>
            ) : (
              <Button size="sm">Connect</Button>
            )}
          </div>
        </div>
      ))}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------
function NotificationsSection() {
  const [emailSummaries, setEmailSummaries] = useState(true);
  const [emailTasks, setEmailTasks] = useState(true);
  const [emailDigest, setEmailDigest] = useState(true);
  const [digestFreq, setDigestFreq] = useState("weekly");
  const [slackTasks, setSlackTasks] = useState(false);
  const [slackMentions, setSlackMentions] = useState(true);

  return (
    <>
      <Section
        title="Email"
        description="Delivered to your registered address."
      >
        <div className="px-5">
          <Row
            title="Meeting summaries"
            description="Right after each meeting ends."
          >
            <Toggle checked={emailSummaries} onChange={setEmailSummaries} />
          </Row>
          <Row
            title="Task assignments"
            description="When an action item is assigned to you."
          >
            <Toggle checked={emailTasks} onChange={setEmailTasks} />
          </Row>
          <Row
            title="Digest"
            description="A rollup of what happened across your team."
          >
            <div className="flex items-center gap-3">
              <Select
                value={digestFreq}
                onChange={setDigestFreq}
                options={[
                  { value: "daily", label: "Daily" },
                  { value: "weekly", label: "Weekly" },
                  { value: "monthly", label: "Monthly" },
                ]}
              />
              <Toggle checked={emailDigest} onChange={setEmailDigest} />
            </div>
          </Row>
        </div>
      </Section>

      <section className="mt-8">
        <Section
          title="Slack"
          description="Requires the Slack integration to be connected."
        >
          <div className="px-5">
            <Row
              title="Task assignments"
              description="DM you when a task is routed to you."
            >
              <Toggle checked={slackTasks} onChange={setSlackTasks} disabled />
            </Row>
            <Row
              title="Mentions in meeting notes"
              description="Alert when your name appears in a summary."
            >
              <Toggle
                checked={slackMentions}
                onChange={setSlackMentions}
                disabled
              />
            </Row>
          </div>
        </Section>
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------
// Security
// ---------------------------------------------------------------------------
function SecuritySection() {
  const [twoFA, setTwoFA] = useState(false);

  const sessions = [
    {
      device: "Chrome on macOS",
      location: "New York, US",
      lastActive: "Active now",
      current: true,
    },
    {
      device: "Safari on iPhone",
      location: "New York, US",
      lastActive: "2 hours ago",
      current: false,
    },
    {
      device: "Firefox on Windows",
      location: "San Francisco, US",
      lastActive: "3 days ago",
      current: false,
    },
  ];

  return (
    <>
      <Section
        title="Password"
        description="Use a strong, unique password."
      >
        <div className="p-5 grid gap-4">
          <Field label="Current password">
            <Input type="password" placeholder="••••••••" className="h-10" />
          </Field>
          <Field label="New password">
            <Input type="password" placeholder="At least 8 characters" className="h-10" />
          </Field>
          <Field label="Confirm new password">
            <Input type="password" placeholder="Repeat new password" className="h-10" />
          </Field>
        </div>
        <div className="-mx-[26px] mt-2 flex items-center justify-end gap-2.5 border-t border-hairline-soft bg-surface-soft px-[26px] py-4">
          <Button size="sm">Update password</Button>
        </div>
      </Section>

      <section className="mt-8">
        <Section
          title="Two-factor authentication"
          description="Extra protection against unauthorized access."
        >
          <div className="px-5">
            <Row
              title="Authenticator app"
              description="Use an app like 1Password or Authy to generate codes."
            >
              <Toggle checked={twoFA} onChange={setTwoFA} />
            </Row>
          </div>
        </Section>
      </section>

      <section className="mt-8">
        <Section
          title="Active sessions"
          description="Devices signed in to your account."
        >
          {sessions.map((s, i) => (
            <div key={i} className="p-5 flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-ink">
                    {s.device}
                  </span>
                  {s.current && (
                    <span className="rounded-full bg-success/12 px-2 py-0.5 text-[10px] font-semibold text-success">
                      This device
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-ink mt-0.5">
                  {s.location} · {s.lastActive}
                </p>
              </div>
              {!s.current && (
                <Button variant="outline" size="sm">
                  Revoke
                </Button>
              )}
            </div>
          ))}
          <div className="-mx-[26px] mt-2 flex justify-end border-t border-hairline-soft bg-surface-soft px-[26px] py-4">
            <Button variant="outline" size="sm">
              Sign out of all other sessions
            </Button>
          </div>
        </Section>
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------
// Billing
// ---------------------------------------------------------------------------
function UsageBar({
  used,
  total,
  label,
  unit,
}: {
  used: number;
  total: number;
  label: string;
  unit: string;
}) {
  const pct = Math.min(100, (used / total) * 100);
  const near = pct >= 80;
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium text-body-strong">{label}</span>
        <span className="text-xs text-muted-ink tabular-nums">
          {used.toLocaleString()} / {total.toLocaleString()} {unit}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-card">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            near ? "bg-warning" : "bg-ink",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function BillingSection() {
  return (
    <>
      <Section
        title="Plan"
        description="Your current subscription and included limits."
      >
        <div className="p-5 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h3 className="vb-title-md text-[19px]">
                Pro Team
              </h3>
              <span className="rounded-full bg-info/12 px-2 py-0.5 text-[10px] font-semibold text-info">
                Current
              </span>
            </div>
            <p className="text-sm text-muted-ink">
              $49 / seat / month · billed monthly
            </p>
          </div>
          <Button variant="outline" size="sm">
            Change plan
          </Button>
        </div>
        <div className="p-5 space-y-4">
          <UsageBar
            label="Transcript minutes"
            used={8420}
            total={20000}
            unit="min"
          />
          <UsageBar
            label="Active meetings this month"
            used={42}
            total={100}
            unit=""
          />
          <UsageBar
            label="Storage"
            used={12}
            total={100}
            unit="GB"
          />
          <UsageBar label="Seats" used={7} total={10} unit="" />
        </div>
      </Section>

      <section className="mt-8">
        <Section
          title="Payment"
          description="Payment method and billing history."
        >
          <div className="p-5 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="inline-flex h-7 w-10 items-center justify-center rounded-xs bg-ink font-mono text-[10px] font-semibold text-on-ink">
                VISA
              </div>
              <div>
                <div className="text-sm font-medium text-ink">
                  •••• •••• •••• 4242
                </div>
                <div className="text-xs text-muted-ink">Expires 12 / 2026</div>
              </div>
            </div>
            <Button variant="outline" size="sm">
              Update
            </Button>
          </div>
          <div className="p-5 flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-ink">
                Billing history
              </div>
              <p className="text-xs text-muted-ink mt-0.5">
                Download past invoices and receipts.
              </p>
            </div>
            <Button variant="outline" size="sm">
              View invoices
              <ExternalLink className="w-3 h-3" />
            </Button>
          </div>
        </Section>
      </section>
    </>
  );
}
