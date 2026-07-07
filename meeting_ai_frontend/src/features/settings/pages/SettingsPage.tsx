import { useState } from "react";
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
import { Input } from "@/components/ui/input";
import { useCurrentUser } from "../../auth/hooks/useCurrentUser";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Small inline primitives — kept in-file since only settings uses them.
// ---------------------------------------------------------------------------
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
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50",
        checked ? "bg-indigo-600" : "bg-slate-300",
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
          checked ? "translate-x-4" : "translate-x-0.5",
        )}
      />
    </button>
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
    <div className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <div className="text-[13px] font-medium text-slate-900">{title}</div>
        {description && (
          <div className="text-xs text-slate-500 mt-0.5">{description}</div>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
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
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-slate-700">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
    </div>
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
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">
          {title}
        </h2>
        <p className="text-sm text-slate-500 mt-1">{description}</p>
      </header>
      <div className="rounded-lg border border-slate-200 bg-white divide-y divide-slate-100">
        {children}
      </div>
    </section>
  );
}

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
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-[13px] text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
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
      <div className="max-w-6xl mx-auto px-8 py-10">
        <header className="mb-10">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-600 mb-1.5">
            Configure
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
            Settings
          </h1>
          <p className="text-sm text-slate-500 mt-2">
            Manage your profile, workspace, AI defaults, and integrations.
          </p>
        </header>

        <div className="grid grid-cols-[220px_1fr] gap-10">
          {/* Section nav */}
          <nav className="sticky top-6 self-start space-y-0.5">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActive(id)}
                className={cn(
                  "w-full flex items-center gap-2.5 px-2.5 h-8 rounded-md text-[13px] font-medium transition-colors group",
                  active === id
                    ? "bg-slate-100 text-slate-900 font-semibold"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-50",
                )}
              >
                <Icon
                  className={cn(
                    "w-4 h-4 shrink-0",
                    active === id ? "text-indigo-600" : "text-slate-400",
                  )}
                  strokeWidth={active === id ? 2.25 : 2}
                />
                <span className="flex-1 text-left">{label}</span>
                {active === id && (
                  <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                )}
              </button>
            ))}
          </nav>

          {/* Section content */}
          <div>
            {active === "profile" && <ProfileSection />}
            {active === "workspace" && <WorkspaceSection />}
            {active === "ai" && <AISection />}
            {active === "integrations" && <IntegrationsSection />}
            {active === "notifications" && <NotificationsSection />}
            {active === "security" && <SecuritySection />}
            {active === "billing" && <BillingSection />}
          </div>
        </div>
      </div>
    </Layout>
  );
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------
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
      <div className="p-5 flex items-center gap-4">
        {user?.google_profile_picture ? (
          <img
            src={user.google_profile_picture}
            alt={user.name}
            className="w-16 h-16 rounded-full object-cover ring-2 ring-slate-200"
          />
        ) : (
          <div className="w-16 h-16 rounded-full bg-gradient-to-br from-indigo-500 to-indigo-700 text-white flex items-center justify-center text-lg font-semibold shadow-sm">
            {initials}
          </div>
        )}
        <div className="flex-1">
          <div className="flex gap-2">
            <Button variant="outline" size="sm">
              Upload photo
            </Button>
            <Button variant="ghost" size="sm">
              Remove
            </Button>
          </div>
          <p className="text-[11px] text-slate-500 mt-2">
            PNG or JPG, up to 2 MB.
          </p>
        </div>
      </div>

      <div className="p-5 grid grid-cols-2 gap-4">
        <Field label="Full name">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-9"
          />
        </Field>
        <Field label="Email" hint="Contact support to change your email.">
          <Input
            value={user?.email || ""}
            readOnly
            className="h-9 bg-slate-50"
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
          <div className="h-9 flex items-center">
            <span className="inline-flex items-center gap-1.5 rounded-md bg-indigo-50 text-indigo-700 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider">
              Org Admin
            </span>
          </div>
        </Field>
      </div>

      <div className="p-4 flex items-center justify-end gap-2 bg-slate-50/60">
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
        <div className="p-5 grid grid-cols-2 gap-4">
          <Field label="Workspace name">
            <Input
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              className="h-9"
            />
          </Field>
          <Field label="Slug" hint="Used in shared meeting links.">
            <Input value="acme" readOnly className="h-9 bg-slate-50" />
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
        <div className="p-4 flex items-center justify-end gap-2 bg-slate-50/60">
          <Button variant="ghost" size="sm">
            Cancel
          </Button>
          <Button size="sm">Save changes</Button>
        </div>
      </Section>

      <section className="mt-8">
        <header className="mb-5">
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">
            Danger zone
          </h2>
          <p className="text-sm text-slate-500 mt-1">
            Irreversible actions. Proceed with care.
          </p>
        </header>
        <div className="rounded-lg border border-red-200 bg-red-50/40 p-5 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-slate-900">
              Delete this workspace
            </div>
            <p className="text-xs text-slate-500 mt-1">
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
      <div className="p-5 grid grid-cols-2 gap-4">
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

      <div className="p-4 flex items-center justify-end gap-2 bg-slate-50/60">
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
          <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center shrink-0">
            <Icon className="w-5 h-5 text-slate-700" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-slate-900">{name}</h3>
              {connected && (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-700 bg-emerald-50 rounded px-1.5 py-0.5">
                  <Check className="w-2.5 h-2.5" strokeWidth={3} />
                  Connected
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">{description}</p>
          </div>
          <div className="shrink-0">
            {locked ? (
              <span className="text-[11px] text-slate-400">System</span>
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
            <Input type="password" placeholder="••••••••" className="h-9" />
          </Field>
          <Field label="New password">
            <Input type="password" placeholder="At least 8 characters" className="h-9" />
          </Field>
          <Field label="Confirm new password">
            <Input type="password" placeholder="Repeat new password" className="h-9" />
          </Field>
        </div>
        <div className="p-4 flex items-center justify-end gap-2 bg-slate-50/60">
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
                  <span className="text-sm font-medium text-slate-900">
                    {s.device}
                  </span>
                  {s.current && (
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700 bg-emerald-50 rounded px-1.5 py-0.5">
                      This device
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 mt-0.5">
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
          <div className="p-4 flex justify-end bg-slate-50/60">
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
        <span className="text-xs font-medium text-slate-700">{label}</span>
        <span className="text-xs text-slate-500 tabular-nums">
          {used.toLocaleString()} / {total.toLocaleString()} {unit}
        </span>
      </div>
      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            near ? "bg-amber-500" : "bg-indigo-600",
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
              <h3 className="text-lg font-semibold text-slate-900">
                Pro Team
              </h3>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 rounded px-1.5 py-0.5">
                Current
              </span>
            </div>
            <p className="text-sm text-slate-500">
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
              <div className="w-10 h-7 rounded bg-slate-900 text-white text-[10px] font-bold flex items-center justify-center">
                VISA
              </div>
              <div>
                <div className="text-sm font-medium text-slate-900">
                  •••• •••• •••• 4242
                </div>
                <div className="text-xs text-slate-500">Expires 12 / 2026</div>
              </div>
            </div>
            <Button variant="outline" size="sm">
              Update
            </Button>
          </div>
          <div className="p-5 flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-slate-900">
                Billing history
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
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
