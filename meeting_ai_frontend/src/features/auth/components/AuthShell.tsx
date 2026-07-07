import {  Zap } from "lucide-react";

/**
 * Split-screen auth shell. Left panel (hidden on mobile) carries the
 * brand + marketing; right panel holds the form.
 */
export default function AuthShell({
  children,
  eyebrow,
  heading,
  subheading,
}: {
  children: React.ReactNode;
  eyebrow: string;
  heading: string;
  subheading: string;
}) {
  return (
    <div className="min-h-screen w-full bg-white grid lg:grid-cols-[1.1fr_1fr]">
      {/* Marketing panel */}
      <aside
        className="relative hidden lg:flex flex-col justify-between p-12 text-white overflow-hidden bg-slate-950"
        style={{
          backgroundImage:
            "radial-gradient(80% 60% at 20% 0%, rgba(99,102,241,0.35), transparent 60%), radial-gradient(60% 50% at 90% 100%, rgba(129,140,248,0.25), transparent 60%)",
        }}
      >
        {/* Subtle grid */}
        <div
          className="absolute inset-0 opacity-[0.06] pointer-events-none"
          style={{
            backgroundImage:
              "linear-gradient(to right, white 1px, transparent 1px), linear-gradient(to bottom, white 1px, transparent 1px)",
            backgroundSize: "48px 48px",
          }}
        />
        {/* Soft top-right glow */}
        <div className="absolute -top-24 -right-24 w-96 h-96 rounded-full bg-indigo-500/20 blur-3xl pointer-events-none" />

        <div className="relative flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-white/10 backdrop-blur flex items-center justify-center ring-1 ring-white/20">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <span className="text-sm font-medium tracking-tight">OrgOS</span>
        </div>

        <div className="relative space-y-6">
          <h2 className="text-4xl font-semibold tracking-tight leading-[1.1] max-w-md">
            Every meeting,{" "}
            <span className="text-indigo-300">quietly organized.</span>
          </h2>
          <p className="text-sm text-white/60 max-w-sm leading-relaxed">
            Transcripts, decisions, and action items — captured, summarized,
            and routed to the people who need them.
          </p>

          <div className="pt-2 space-y-3 text-sm text-white/70">
            {[
              "Live transcription during the call",
              "Auto-extracted decisions & tasks",
              "Ask questions across every meeting",
            ].map((f) => (
              <div key={f} className="flex items-center gap-3">
                <span className="w-1 h-1 rounded-full bg-indigo-300" />
                <span>{f}</span>
              </div>
            ))}
          </div>
        </div>

        <p className="relative text-xs text-white/40">
          © {new Date().getFullYear()} OrgOS Meeting Assistant
        </p>
      </aside>

      {/* Form panel */}
      <main className="relative flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-10">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-600 mb-2">
              {eyebrow}
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
              {heading}
            </h1>
            <p className="text-sm text-slate-500 mt-2">{subheading}</p>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
