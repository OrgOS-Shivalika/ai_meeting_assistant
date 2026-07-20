import { forwardRef } from "react";

/**
 * Split-screen auth shell — reskinned to the Appu / vibrant design
 * tokens. Left panel (hidden on mobile) is the dark teal-black surface
 * with soft pink/lavender blob gradients + spark logo. Right panel
 * holds the form, over a warm cream canvas.
 *
 * The two auth pages (Login, Register) share this shell AND consume the
 * `VbTextInput` + `VbButton` primitives exported below, so both stay
 * visually consistent without a new global primitives directory.
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
  /** Which pair of accent blobs the left panel renders — matches the
   *  mockups: login uses pink + lavender; register uses lavender + pink
   *  swapped. Cosmetic only. */
  variant?: "login" | "register";
}) {
  const isLogin = variant === "login";
  return (
    <div
      className="min-h-screen w-full grid lg:grid-cols-[1.1fr_1fr]"
      style={{
        background: "var(--vb-canvas)",
        fontFamily: "var(--vb-font-sans)",
        color: "var(--vb-body)",
      }}
    >
      {/* Marketing panel — dark teal-black with soft blob gradients */}
      <aside
        className="relative hidden lg:flex flex-col justify-between p-12 overflow-hidden"
        style={{
          background: "var(--vb-surface-dark)",
          color: "var(--vb-on-ink)",
        }}
      >
        {/* Blob glows — top-right + bottom-left, swap colors per variant */}
        <div
          className="absolute -top-32 -right-32 w-96 h-96 rounded-full pointer-events-none"
          style={{
            background: `color-mix(in srgb, ${isLogin ? "var(--vb-pink)" : "var(--vb-lavender)"} 35%, transparent)`,
            filter: "blur(80px)",
          }}
        />
        <div
          className="absolute -bottom-24 -left-16 w-80 h-80 rounded-full pointer-events-none"
          style={{
            background: `color-mix(in srgb, ${isLogin ? "var(--vb-lavender)" : "var(--vb-pink)"} 30%, transparent)`,
            filter: "blur(80px)",
          }}
        />

        {/* Logo — pink spark with peach inner */}
        <div className="relative flex items-center gap-2.5">
          <span
            className="inline-flex items-center justify-center"
            style={{
              width: 32,
              height: 32,
              borderRadius: 9,
              background: "var(--vb-pink)",
            }}
          >
            <span
              style={{
                width: 13,
                height: 13,
                borderRadius: 4,
                background: "var(--vb-peach)",
              }}
            />
          </span>
          <span
            style={{
              fontFamily: "var(--vb-font-display)",
              fontWeight: 600,
              fontSize: 16,
              letterSpacing: "-0.5px",
            }}
          >
            OrgOS
          </span>
        </div>

        <div className="relative">
          <h2
            className="mb-5"
            style={{
              fontFamily: "var(--vb-font-display)",
              fontWeight: 500,
              fontSize: 40,
              lineHeight: 1.1,
              letterSpacing: "-1.4px",
              maxWidth: 440,
            }}
          >
            {isLogin
              ? "Every meeting, quietly organized."
              : "Set up your workspace in a minute."}
          </h2>
          <p
            className="mb-6"
            style={{
              fontSize: 15,
              lineHeight: 1.6,
              color: "var(--vb-on-ink-soft)",
              maxWidth: 380,
            }}
          >
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
              ].map((f) => (
                <div
                  key={f.text}
                  className="flex items-center gap-3 text-sm"
                  style={{ color: "var(--vb-on-ink-soft)" }}
                >
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: "50%",
                      background: f.color,
                    }}
                  />
                  {f.text}
                </div>
              ))}
            </div>
          )}
        </div>

        <p
          className="relative"
          style={{
            fontSize: 12,
            color: "var(--vb-on-ink-soft)",
            opacity: 0.7,
          }}
        >
          © {new Date().getFullYear()} OrgOS Meeting Assistant
        </p>
      </aside>

      {/* Form panel */}
      <main className="relative flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-9">
            <p
              className="mb-2.5"
              style={{
                fontSize: 12,
                fontWeight: 600,
                letterSpacing: "1.5px",
                textTransform: "uppercase",
                color: "var(--vb-pink)",
              }}
            >
              {eyebrow}
            </p>
            <h1
              style={{
                fontFamily: "var(--vb-font-display)",
                fontWeight: 500,
                fontSize: 34,
                letterSpacing: "-1.2px",
                color: "var(--vb-ink)",
              }}
            >
              {heading}
            </h1>
            <p
              className="mt-2.5"
              style={{ fontSize: 14, color: "var(--vb-muted)" }}
            >
              {subheading}
            </p>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Vibrant form primitives — colocated here so both auth pages share them
 * without forking a global primitives module until we know the pattern
 * generalizes across more screens.
 * ------------------------------------------------------------------------- */

const inputStyle: React.CSSProperties = {
  height: 44,
  boxSizing: "border-box",
  padding: "0 14px",
  fontFamily: "var(--vb-font-sans)",
  fontSize: 14,
  background: "var(--vb-canvas)",
  border: "1px solid var(--vb-hairline)",
  borderRadius: 12,
  color: "var(--vb-ink)",
  outline: "none",
  width: "100%",
  transition: "border-color 160ms ease, box-shadow 160ms ease",
};

export const VbTextInput = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function VbTextInput({ style, onFocus, onBlur, ...rest }, ref) {
    return (
      <input
        ref={ref}
        {...rest}
        style={{ ...inputStyle, ...style }}
        onFocus={(e) => {
          e.currentTarget.style.borderColor = "var(--vb-ink)";
          e.currentTarget.style.boxShadow = "0 0 0 3px var(--focus-ring)";
          onFocus?.(e);
        }}
        onBlur={(e) => {
          e.currentTarget.style.borderColor = "var(--vb-hairline)";
          e.currentTarget.style.boxShadow = "none";
          onBlur?.(e);
        }}
      />
    );
  },
);

export function VbLabel({ children }: { children: React.ReactNode }) {
  return (
    <label
      style={{
        fontSize: 12,
        fontWeight: 500,
        color: "var(--vb-body-strong)",
      }}
    >
      {children}
    </label>
  );
}

export function VbButton({
  children,
  disabled,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      disabled={disabled}
      style={{
        height: 44,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        width: "100%",
        background: disabled ? "var(--vb-ink-disabled)" : "var(--vb-ink)",
        color: disabled ? "var(--vb-muted)" : "var(--vb-on-ink)",
        border: "none",
        borderRadius: 12,
        fontSize: 14,
        fontWeight: 500,
        fontFamily: "var(--vb-font-sans)",
        cursor: disabled ? "not-allowed" : "pointer",
        transition: "background 160ms ease",
        ...(rest.style ?? {}),
      }}
      onMouseDown={(e) => {
        if (!disabled) e.currentTarget.style.background = "var(--vb-ink-active)";
      }}
      onMouseUp={(e) => {
        if (!disabled) e.currentTarget.style.background = "var(--vb-ink)";
      }}
      onMouseLeave={(e) => {
        if (!disabled) e.currentTarget.style.background = "var(--vb-ink)";
      }}
    >
      {children}
    </button>
  );
}
