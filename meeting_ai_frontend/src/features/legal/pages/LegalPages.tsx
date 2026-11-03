import { Link } from "react-router-dom";
import {
  ArrowRight,
  Ban,
  CalendarDays,
  Check,
  FileText,
  FolderOpen,
  ListChecks,
  Mail,
  Mic,
  Search,
  ShieldCheck,
  Sparkles,
  Unplug,
  Video,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { accent, tint } from "@/lib/vibrant";

/**
 * Public pages Google's OAuth consent screen links to: home, privacy, terms.
 * No auth — Google's reviewers open them signed out. Keep the Google data
 * section of the privacy policy in step with the scopes in
 * app/services/google_service.py and drive_export_service.DRIVE_SCOPE.
 */

const APP = "OrgOS Meeting Assistant";
const COMPANY = "imagine.bo";
const CONTACT = "divyansh@imagine.bo"; // ponytail: swap for a support@ inbox when one exists
const UPDATED = "3 November 2026";

const link = "font-semibold text-ink underline-offset-4 hover:underline";

function Mark() {
  return (
    <Link to="/home" className="flex items-center gap-[11px]">
      <span className="inline-flex size-8 items-center justify-center rounded-[9px] bg-pink">
        <span className="size-[13px] rounded-[4px] bg-peach" />
      </span>
      <span className="font-display text-base font-semibold tracking-[-0.5px] text-ink">OrgOS</span>
    </Link>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas text-body">
      <header className="sticky top-0 z-10 border-b border-hairline-soft bg-canvas/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Mark />
          <nav className="flex items-center gap-1 sm:gap-2">
            <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
              <Link to="/privacy">Privacy</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
              <Link to="/terms">Terms</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/login">Sign in</Link>
            </Button>
            <Button size="sm" asChild>
              <Link to="/register">Get started</Link>
            </Button>
          </nav>
        </div>
      </header>
      {children}
      <footer className="border-t border-hairline">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-[13px] text-muted-ink sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span>
            © {new Date().getFullYear()} {COMPANY} · {APP}
          </span>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            <Link to="/home" className="hover:text-ink">Home</Link>
            <Link to="/privacy" className="hover:text-ink">Privacy Policy</Link>
            <Link to="/terms" className="hover:text-ink">Terms of Service</Link>
            <a href={`mailto:${CONTACT}`} className="hover:text-ink">{CONTACT}</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

// ─── Home ────────────────────────────────────────────────────────────────────

const FEATURES = [
  { icon: Mic, title: "Live transcription", text: "A notetaker joins Google Meet, Zoom and Teams calls and transcribes them as they happen — Hindi and Hinglish included." },
  { icon: Sparkles, title: "Summaries & decisions", text: "Every meeting ends with a clear summary and the decisions that were actually made." },
  { icon: ListChecks, title: "Action items, routed", text: "Tasks are pulled out with owners and due dates and land on your team's boards." },
  { icon: Search, title: "Ask across meetings", text: "Ask a question and get the answer from every meeting your team has had, with sources." },
  { icon: CalendarDays, title: "Calendar-aware", text: "Connect Google Calendar and the notetaker shows up to your scheduled calls on its own." },
  { icon: FolderOpen, title: "Transcripts in Drive", text: "Optionally save every transcript as a Google Doc in a Meeting Transcripts folder." },
];

const STEPS = [
  { title: "Connect your calendar", text: "Sign in and connect Google. Your upcoming meetings appear automatically." },
  { title: "Meet as usual", text: "The notetaker joins, listens and transcribes. Nothing to install for your guests." },
  { title: "Get the follow-through", text: "Summary, decisions and tasks arrive minutes after the call ends." },
];

function Preview() {
  return (
    <Card variant="default" className="rounded-2xl p-5 shadow-raised sm:p-6">
      <div className="mb-4 flex items-center gap-3">
        <span className="inline-flex size-9 items-center justify-center rounded-md" style={{ background: tint(accent(1), 14), color: accent(1) }}>
          <Video className="size-[18px]" />
        </span>
        <div className="min-w-0">
          <p className="vb-title-sm truncate">Anko Kmart — SS27 cushion covers</p>
          <p className="text-xs text-muted-ink">Google Meet · 42 min · 5 attendees</p>
        </div>
      </div>
      <p className="vb-label-caps mb-1.5">Summary</p>
      <p className="mb-4 text-[13px] leading-relaxed">
        Buyer confirmed BCI cotton for the SS27 range. Pricing agreed for two colourways; lab dips due before sampling.
      </p>
      <p className="vb-label-caps mb-2">Action items</p>
      <ul className="space-y-2">
        {[
          ["Send BCI certificate to buyer", "Ravi · Fri"],
          ["Share lab dips for both colourways", "Sunil · Nov 12"],
          ["Revise costing sheet", "Priya · Mon"],
        ].map(([task, meta]) => (
          <li key={task} className="flex items-center gap-2.5 rounded-md bg-surface-soft px-3 py-2 text-[13px]">
            <span className="inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-success/15 text-success">
              <Check className="size-3" />
            </span>
            <span className="min-w-0 flex-1 truncate text-ink">{task}</span>
            <span className="shrink-0 text-xs text-muted-ink">{meta}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function HomePage() {
  return (
    <Shell>
      {/* Hero */}
      <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pt-14 pb-16 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-20 lg:pb-24">
        <div>
          <p className="vb-eyebrow mb-4">AI meeting assistant</p>
          <h1 className="mb-5 font-display text-[40px] leading-[1.05] font-medium tracking-[-1.6px] text-ink sm:text-[54px] sm:tracking-[-2px]">
            Every meeting, quietly organized.
          </h1>
          <p className="mb-8 max-w-[480px] text-[16px] leading-relaxed text-muted-ink">
            OrgOS joins your calls, transcribes them, and turns each one into a summary, the decisions made and the
            action items — routed to the people who need them.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button size="lg" asChild>
              <Link to="/register">
                Get started <ArrowRight />
              </Link>
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link to="/login">Sign in</Link>
            </Button>
          </div>
        </div>
        <div className="relative">
          <div className="pointer-events-none absolute -top-8 -right-6 size-64 rounded-full bg-lavender/40 blur-[70px]" />
          <div className="pointer-events-none absolute -bottom-10 -left-8 size-56 rounded-full bg-pink/25 blur-[70px]" />
          <div className="relative">
            <Preview />
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
        <p className="vb-eyebrow mb-3">What it does</p>
        <h2 className="vb-display-sm mb-8 max-w-[560px]">The notes, the tasks and the follow-through — handled.</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text }, i) => (
            <Card key={title} variant="default" className="rounded-xl p-6">
              <span className="mb-4 inline-flex size-10 items-center justify-center rounded-md" style={{ background: tint(accent(i), 14), color: accent(i) }}>
                <Icon className="size-[19px]" />
              </span>
              <h3 className="vb-title-md">{title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted-ink">{text}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* How it works — the lavender feature card */}
      <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
        <div className="relative overflow-hidden rounded-3xl bg-lavender p-8 sm:p-11">
          <div className="pointer-events-none absolute -top-10 -right-5 size-56 rounded-full bg-white/25" />
          <p className="relative mb-3 text-xs font-semibold tracking-[1.5px] text-ink/70 uppercase">How it works</p>
          <h2 className="relative mb-8 font-display text-[32px] leading-[1.1] font-medium tracking-[-1px] text-ink">
            Three steps, then it runs itself.
          </h2>
          <ol className="relative grid gap-4 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="rounded-xl bg-white/55 p-5">
                <span className="mb-3 inline-flex size-8 items-center justify-center rounded-full bg-ink font-display text-sm text-on-ink">
                  {i + 1}
                </span>
                <h3 className="vb-title-md">{s.title}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-ink/75">{s.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Google data — what reviewers and users look for */}
      <section className="mx-auto grid max-w-6xl gap-8 px-4 pb-20 sm:px-6 lg:grid-cols-[1fr_1.2fr]">
        <div>
          <p className="vb-eyebrow mb-3">Your data</p>
          <h2 className="vb-display-sm mb-4">Google access, only for what you turn on.</h2>
          <p className="text-[15px] leading-relaxed text-muted-ink">
            Every Google permission is optional and used only to provide the feature it belongs to. We never sell your
            data or use it to train AI models. Disconnect any time from the Integrations page. Read the{" "}
            <Link to="/privacy" className={link}>Privacy Policy</Link>.
          </p>
        </div>
        <Card variant="default" className="divide-y divide-hairline-soft rounded-xl px-6">
          {[
            ["Google Calendar", "Read your scheduled meetings so the notetaker can join; create events with Meet links when you schedule from OrgOS."],
            ["Google Meet", "Configure Meet spaces the app creates so the notetaker can join."],
            ["Google Drive", "Only if you connect it: write one Google Doc per meeting into a folder the app creates. No access to your other files."],
          ].map(([name, text]) => (
            <div key={name} className="py-5">
              <h3 className="vb-title-sm">{name}</h3>
              <p className="mt-1 text-[13px] leading-relaxed text-muted-ink">{text}</p>
            </div>
          ))}
        </Card>
      </section>

      {/* Closing CTA — the dark glow panel from the sign-in screen */}
      <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
        <div className="relative overflow-hidden rounded-3xl bg-surface-dark p-8 text-on-ink sm:p-12">
          <div className="pointer-events-none absolute -top-32 -right-32 size-96 rounded-full blur-[80px]" style={{ background: "color-mix(in srgb, var(--vb-pink) 35%, transparent)" }} />
          <div className="pointer-events-none absolute -bottom-24 -left-16 size-80 rounded-full blur-[80px]" style={{ background: "color-mix(in srgb, var(--vb-lavender) 30%, transparent)" }} />
          <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="mb-2 font-display text-[32px] leading-[1.1] font-medium tracking-[-1px]">Bring it to your next call.</h2>
              <p className="text-[15px] text-on-ink-soft">Set up your workspace in a minute.</p>
            </div>
            <Button size="lg" variant="onColor" asChild>
              <Link to="/register">
                Get started <ArrowRight />
              </Link>
            </Button>
          </div>
        </div>
      </section>
    </Shell>
  );
}

// ─── Legal ───────────────────────────────────────────────────────────────────

type Section = { id: string; title: string; body: React.ReactNode };
type Glance = { icon: React.ComponentType<{ className?: string }>; title: string; text: string };

const prose =
  "space-y-3.5 text-[15px] leading-relaxed [&_b]:font-semibold [&_b]:text-ink [&_li]:relative [&_li]:pl-5 [&_li]:before:absolute [&_li]:before:left-0 [&_li]:before:top-[0.6em] [&_li]:before:size-1.5 [&_li]:before:rounded-full [&_li]:before:bg-pink [&_ul]:space-y-2.5";

function LegalDoc({
  title,
  intro,
  hue,
  glance,
  sections,
}: {
  title: string;
  intro: React.ReactNode;
  hue: "bg-lavender" | "bg-peach";
  glance: Glance[];
  sections: Section[];
}) {
  return (
    <Shell>
      <div className="mx-auto max-w-6xl px-4 pt-8 pb-20 sm:px-6 sm:pt-12">
        {/* Header — saturated feature card */}
        <header className={`relative mb-6 overflow-hidden rounded-3xl ${hue} p-8 sm:p-12`}>
          <div className="pointer-events-none absolute -top-12 -right-8 size-64 rounded-full bg-white/25" />
          <div className="pointer-events-none absolute -bottom-20 right-40 size-40 rounded-full bg-white/15" />
          <div className="relative max-w-[620px]">
            <p className="mb-3.5 text-xs font-semibold tracking-[1.5px] text-ink/70 uppercase">Legal</p>
            <h1 className="mb-4 font-display text-[40px] leading-[1.05] font-medium tracking-[-1.6px] text-ink sm:text-[48px]">
              {title}
            </h1>
            <p className="mb-6 text-[15px] leading-relaxed text-ink/80">{intro}</p>
            <span className="inline-flex items-center gap-2 rounded-full bg-white/60 px-3.5 py-1.5 text-xs font-semibold text-ink">
              <span className="size-1.5 rounded-full bg-ink" />
              Last updated {UPDATED}
            </span>
          </div>
        </header>

        {/* At a glance */}
        <div className="mb-14 grid gap-4 sm:grid-cols-3">
          {glance.map(({ icon: Icon, title: t, text }, i) => (
            <Card key={t} variant="default" className="rounded-xl p-5">
              <span className="mb-3 inline-flex size-9 items-center justify-center rounded-md" style={{ background: tint(accent(i), 14), color: accent(i) }}>
                <Icon className="size-[18px]" />
              </span>
              <h2 className="vb-title-sm">{t}</h2>
              <p className="mt-1 text-[13px] leading-relaxed text-muted-ink">{text}</p>
            </Card>
          ))}
        </div>

        <div className="grid gap-10 lg:grid-cols-[230px_1fr]">
          {/* Contents */}
          <aside className="hidden lg:block">
            <nav className="sticky top-24">
              <p className="vb-label-caps mb-3">On this page</p>
              <ol className="space-y-0.5 border-l border-hairline">
                {sections.map((s, i) => (
                  <li key={s.id}>
                    <a href={`#${s.id}`} className="-ml-px flex gap-2.5 border-l border-transparent py-1.5 pl-4 text-[13px] text-muted-ink transition-colors hover:border-ink hover:text-ink">
                      <span className="font-mono text-muted-soft">{String(i + 1).padStart(2, "0")}</span>
                      {s.title}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          </aside>

          <main className="min-w-0">
            {sections.map((s, i) => (
              <section key={s.id} id={s.id} className="scroll-mt-24 border-b border-hairline-soft py-9 first:pt-0 last:border-0">
                <div className="mb-4 flex items-center gap-3.5">
                  <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-full font-mono text-[13px] font-semibold" style={{ background: tint(accent(i), 16), color: accent(i) }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h2 className="vb-title-lg">{s.title}</h2>
                </div>
                <div className={`${prose} sm:pl-[50px]`}>{s.body}</div>
              </section>
            ))}

            {/* Contact */}
            <div className="relative mt-6 overflow-hidden rounded-2xl bg-surface-dark p-7 text-on-ink sm:p-9">
              <div className="pointer-events-none absolute -top-24 -right-24 size-72 rounded-full blur-[70px]" style={{ background: "color-mix(in srgb, var(--vb-pink) 35%, transparent)" }} />
              <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="font-display text-[24px] font-medium tracking-[-0.5px]">Questions about this?</h2>
                  <p className="mt-1 text-sm text-on-ink-soft">Write to us and a person will reply.</p>
                </div>
                <Button variant="onColor" asChild>
                  <a href={`mailto:${CONTACT}`}>
                    <Mail /> {CONTACT}
                  </a>
                </Button>
              </div>
            </div>
          </main>
        </div>
      </div>
    </Shell>
  );
}

function Callout({ icon: Icon, children }: { icon: React.ComponentType<{ className?: string }>; children: React.ReactNode }) {
  return (
    <div className="flex gap-3.5 rounded-xl p-4 sm:p-5" style={{ background: tint("var(--vb-info)", 10) }}>
      <Icon className="mt-0.5 size-5 shrink-0 text-info" />
      <div className="text-[14px] leading-relaxed text-ink">{children}</div>
    </div>
  );
}

function Rows({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <div className="divide-y divide-hairline-soft overflow-hidden rounded-xl border border-hairline">
      {items.map(([name, text]) => (
        <div key={name} className="grid gap-1 bg-canvas px-4 py-3.5 sm:grid-cols-[170px_1fr] sm:gap-4">
          <span className="text-[14px] font-semibold text-ink">{name}</span>
          <span className="text-[14px] text-body">{text}</span>
        </div>
      ))}
    </div>
  );
}

const scope = (s: string) => (
  <code className="rounded-sm bg-surface-card px-1.5 py-0.5 font-mono text-[12px] text-ink">{s}</code>
);

export function PrivacyPage() {
  return (
    <LegalDoc
      title="Privacy Policy"
      hue="bg-lavender"
      intro={<>What {APP} collects, how we use it, and the choices you have. Plain language, no surprises.</>}
      glance={[
        { icon: Ban, title: "Never sold", text: "We don't sell your data or use it for advertising." },
        { icon: ShieldCheck, title: "No AI training", text: "Your Google data is never used to train AI models." },
        { icon: Unplug, title: "Disconnect anytime", text: "Remove Google access in one click; we delete the tokens." },
      ]}
      sections={[
        {
          id: "collect",
          title: "Information we collect",
          body: (
            <ul>
              <li><b>Account details</b>: your name, email address and password (stored hashed), and your organization.</li>
              <li><b>Meeting content</b>: audio of meetings our notetaker joins, the resulting transcript, participant names, and the summaries, decisions and tasks generated from it.</li>
              <li><b>Google account data</b>, only if you connect Google — see the next section.</li>
              <li><b>Usage data</b>: logs needed to run, secure and debug the service.</li>
            </ul>
          ),
        },
        {
          id: "google",
          title: "Google user data",
          body: (
            <>
              <p>When you connect your Google account, you choose to grant these permissions:</p>
              <Rows
                items={[
                  ["Profile & email", <>{scope("userinfo.email")} {scope("userinfo.profile")} {scope("openid")} — to identify your account and show your name and photo.</>],
                  ["Google Calendar", <>{scope("calendar.readonly")} {scope("calendar.events")} — we read your upcoming events (title, time, meeting link, attendees) to send our notetaker and title your meetings, and create events with Meet links when you schedule from the app. We never change or delete events we did not create.</>],
                  ["Google Meet", <>{scope("meetings.space.created")} — to configure the Meet spaces the app creates so the notetaker can join.</>],
                  ["Google Drive", <>{scope("drive.file")} — only if you click "Connect Google Drive". We create a "Meeting Transcripts" folder and write one Google Doc per meeting. We cannot see or read any other file in your Drive.</>],
                ]}
              />
              <p>
                We use Google user data only to provide and improve these user-facing features. We do not sell it, do not
                use it for advertising, and do not use it to train generalized AI or machine-learning models. Humans at{" "}
                {COMPANY} do not read it unless you ask us to (for support), it is needed for security or abuse
                investigation, or the law requires it.
              </p>
              <Callout icon={ShieldCheck}>
                {APP}'s use and transfer of information received from Google APIs to any other app will adhere to the{" "}
                <a href="https://developers.google.com/terms/api-services-user-data-policy" className={link} target="_blank" rel="noreferrer">
                  Google API Services User Data Policy
                </a>
                , including the Limited Use requirements.
              </Callout>
            </>
          ),
        },
        {
          id: "use",
          title: "How we use information",
          body: (
            <ul>
              <li>To record, transcribe and summarize your meetings and extract decisions and action items.</li>
              <li>To share a meeting's notes and tasks with members of your organization who have access to it. Members of your organization who were on the calendar invite and have connected Google Drive also get the meeting's Google Doc in their own Drive.</li>
              <li>To send account emails: invitations, password resets, and task notifications (assignments, mentions, due dates).</li>
              <li>To keep the service secure and working.</li>
            </ul>
          ),
        },
        {
          id: "providers",
          title: "Service providers",
          body: (
            <>
              <p>We share data only with providers that process it on our behalf to run the service:</p>
              <Rows
                items={[
                  ["Recall.ai", "The meeting notetaker that joins calls and captures audio."],
                  ["Deepgram, AssemblyAI", "Speech-to-text transcription."],
                  ["OpenAI", "Summaries, decisions, tasks and answers. Data sent through its API is not used to train its models."],
                  ["Railway", "Hosting and database."],
                  ["Email provider", "Delivering account and meeting emails."],
                ]}
              />
              <p>We may also disclose information if the law requires it.</p>
            </>
          ),
        },
        {
          id: "retention",
          title: "Retention and deletion",
          body: (
            <>
              <p>We keep meeting data for as long as your organization's account is active.</p>
              <ul>
                <li>Disconnect Google any time from the Integrations page — this deletes the Google tokens we hold.</li>
                <li>
                  Or revoke access from your Google account at{" "}
                  <a href="https://myaccount.google.com/permissions" className={link} target="_blank" rel="noreferrer">myaccount.google.com/permissions</a>.
                </li>
                <li>Docs already written to your Drive stay there and are yours.</li>
                <li>To delete your account or data, email <a href={`mailto:${CONTACT}`} className={link}>{CONTACT}</a> — done within 30 days.</li>
              </ul>
            </>
          ),
        },
        {
          id: "security",
          title: "Security",
          body: (
            <p>
              Data is encrypted in transit (HTTPS) and access is limited to your organization by role. Google access tokens are stored on our servers, used only by our servers, and never shown to other users. No system is
              perfectly secure, but we work to protect your data and will notify you of a breach that affects it as the
              law requires.
            </p>
          ),
        },
        {
          id: "changes",
          title: "Changes",
          body: <p>We will post changes here and update the date above. Material changes will be notified by email.</p>,
        },
      ]}
    />
  );
}

export function TermsPage() {
  return (
    <LegalDoc
      title="Terms of Service"
      hue="bg-peach"
      intro={<>The rules for using {APP}, operated by {COMPANY}. By creating an account or using the service you agree to them.</>}
      glance={[
        { icon: Mic, title: "Get consent", text: "Tell participants before a meeting is recorded." },
        { icon: FileText, title: "Your content is yours", text: "We only use it to run the service for you." },
        { icon: Sparkles, title: "Check AI output", text: "Summaries and tasks can be wrong — verify what matters." },
      ]}
      sections={[
        {
          id: "accounts",
          title: "Accounts",
          body: (
            <p>
              You must give accurate information and keep your password secure. You are responsible for activity on
              your account. Organization admins control who joins their workspace and what members can see.
            </p>
          ),
        },
        {
          id: "consent",
          title: "Recording consent",
          body: (
            <Callout icon={Mic}>
              The service records and transcribes meetings. You are responsible for telling participants and obtaining
              any consent the law requires before the notetaker records a meeting.
            </Callout>
          ),
        },
        {
          id: "use",
          title: "Acceptable use",
          body: (
            <ul>
              <li>Do not use the service for anything unlawful, or to record people without the consent the law requires.</li>
              <li>Do not try to access other organizations' data, disrupt the service, or reverse-engineer it.</li>
              <li>Do not resell the service without our written permission.</li>
            </ul>
          ),
        },
        {
          id: "content",
          title: "Your content",
          body: (
            <p>
              You own your meeting content. You grant us the rights needed to host, process and display it to provide
              the service, as described in our <Link to="/privacy" className={link}>Privacy Policy</Link>.
            </p>
          ),
        },
        {
          id: "ai",
          title: "AI-generated output",
          body: (
            <p>
              Transcripts, summaries, decisions and tasks are generated automatically and can be wrong or incomplete.
              Check anything important before relying on it.
            </p>
          ),
        },
        {
          id: "third-party",
          title: "Third-party services",
          body: (
            <p>
              Connecting Google Calendar, Google Meet or Google Drive is optional and also subject to Google's terms. You
              can disconnect at any time.
            </p>
          ),
        },
        {
          id: "termination",
          title: "Termination",
          body: (
            <p>
              You can stop using the service at any time. We may suspend or end access for breach of these terms. On
              request we delete your data as set out in the Privacy Policy.
            </p>
          ),
        },
        {
          id: "liability",
          title: "Disclaimer and liability",
          body: (
            <p>
              The service is provided "as is" without warranties. To the extent the law allows, we are not liable for
              indirect or consequential losses, and our total liability is limited to the amount you paid us in the 12
              months before the claim.
            </p>
          ),
        },
        {
          id: "changes",
          title: "Changes",
          body: <p>We may update these terms and will post the new version here.</p>,
        },
      ]}
    />
  );
}
