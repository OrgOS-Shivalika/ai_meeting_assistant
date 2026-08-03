import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * Split-screen auth shell. Left panel (hidden on mobile) is the rare dark
 * teal-black surface with soft pink/lavender blob glows and the spark
 * logo; right panel holds the form over the warm cream canvas.
 */
export default function AuthShell({
  children,
  eyebrow,
  heading,
  subheading,
  variant = "login",
}: {
  children: React.ReactNode;
  eyebrow: string;
  heading: string;
  subheading: string;
  /** Which pair of accent blobs the left panel renders — login leads with
   *  pink, register with lavender. Cosmetic only. */
  variant?: "login" | "register";
}) {
  const isLogin = variant === "login";
  return (
    <div className="grid min-h-screen w-full bg-canvas text-body lg:grid-cols-[1.1fr_1fr]">
      {/* Marketing panel */}
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-surface-dark p-12 text-on-ink lg:flex">
        <div
          className="pointer-events-none absolute -top-32 -right-32 size-96 rounded-full blur-[80px]"
          style={{
            background: `color-mix(in srgb, ${isLogin ? "var(--vb-pink)" : "var(--vb-lavender)"} 35%, transparent)`,
          }}
        />
        <div
          className="pointer-events-none absolute -bottom-24 -left-16 size-80 rounded-full blur-[80px]"
          style={{
            background: `color-mix(in srgb, ${isLogin ? "var(--vb-lavender)" : "var(--vb-pink)"} 30%, transparent)`,
          }}
        />

        {/* Spark mark — pink square with a peach inner spark. */}
        <div className="relative flex items-center gap-[11px]">
          <span className="inline-flex size-8 items-center justify-center rounded-[9px] bg-pink">
            <span className="size-[13px] rounded-[4px] bg-peach" />
          </span>
          <span className="font-display text-base font-semibold tracking-[-0.5px]">
            OrgOS
          </span>
        </div>

        <div className="relative">
          <h2 className="mb-5 max-w-[440px] font-display text-[40px] leading-[1.1] font-medium tracking-[-1.4px]">
            {isLogin
              ? "Every meeting, quietly organized."
              : "Set up your workspace in a minute."}
          </h2>
          <p className="mb-6 max-w-[380px] text-[15px] leading-relaxed text-on-ink-soft">
            {isLogin
              ? "Transcripts, decisions and action items — captured, summarized and routed to the people who need them."
              : "Bring the bot to your next call and let it handle the notes, the tasks and the follow-through."}
          </p>
          {isLogin && (
            <div className="flex flex-col gap-3">
              {[
                { color: "var(--vb-pink)", text: "Live transcription during the call" },
                { color: "var(--vb-peach)", text: "Auto-extracted decisions & tasks" },
                { color: "var(--vb-lavender)", text: "Ask questions across every meeting" },
              ].map((feature) => (
                <div
                  key={feature.text}
                  className="flex items-center gap-3 text-sm text-on-ink-soft"
                >
                  <span
                    className="size-1.5 rounded-full"
                    style={{ background: feature.color }}
                  />
                  {feature.text}
                </div>
              ))}
            </div>
          )}
        </div>

        <p className="relative text-xs text-on-ink-soft opacity-70">
          © {new Date().getFullYear()} OrgOS Meeting Assistant
        </p>
      </aside>

      {/* Form panel */}
      <main className="relative flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-9">
            <p className="vb-eyebrow mb-2.5">{eyebrow}</p>
            <h1 className="font-display text-[34px] font-medium tracking-[-1.2px] text-ink">
              {heading}
            </h1>
            <p className="mt-2.5 text-sm text-muted-ink">{subheading}</p>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}

/**
 * Password input with the show/hide eye. Lives here because it's an
 * auth-only affordance — everything else uses `Input` directly.
 */
export function PasswordInput({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input
        {...props}
        type={visible ? "text" : "password"}
        className={cn("pr-11", className)}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        disabled={props.disabled}
        className="absolute top-1/2 right-3.5 -translate-y-1/2 text-muted-soft transition-colors hover:text-body disabled:opacity-50"
        aria-label={visible ? "Hide password" : "Show password"}
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
}

/** Inline form error — soft error wash, hairline in the same hue. */
export function AuthError({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 rounded-md border border-error/25 bg-error/8 p-3">
      <span className="mt-0.5 size-1.5 shrink-0 rounded-full bg-error" />
      <p className="text-xs leading-relaxed text-error">{children}</p>
    </div>
  );
}

/** Checkbox + label row used for "keep me signed in" / terms consent. */
export function AuthCheckbox({
  checked,
  onChange,
  disabled,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed text-muted-ink select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
        className="mt-0.5 size-3.5 shrink-0 cursor-pointer accent-ink disabled:opacity-50"
      />
      <span>{children}</span>
    </label>
  );
}
