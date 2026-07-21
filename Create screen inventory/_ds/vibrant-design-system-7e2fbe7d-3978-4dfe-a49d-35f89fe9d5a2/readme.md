# Appu — Design System

**Appu** is an **agentic AI CRM**: a multi-tenant SaaS that a business owner or
partner can *build, bootstrap, operate, and modify by talking to an LLM* over MCP.
It pairs an omnichannel chatbot + voicebot, an ML cohort/scoring engine, and a
hyper-personalization agent-messaging system to capture, qualify, nurture, and
close leads across WhatsApp, ads, email, and calendar.

This design system gives design agents everything needed to build well-branded
Appu interfaces and assets — tokens, fonts, logo, reusable components, and
full product + marketing UI kits.

> **The brand in one line:** a cream-canvas, claymation-warm take on B2B SaaS —
> saturated single-color feature cards, near-black CTAs, and a friendly rounded
> display face. Warm where the category is cool.

## Sources

This system was built from materials the user provided. If you have access, explore them to go deeper:

- **Product PRD / scope** — GitHub: `RaahullL277/CRM`, `docs/` (mirrored under [`/docs`](./docs) here; start with [`docs/PRD-README.md`](./docs/PRD-README.md)). Browse the repo: https://github.com/RaahullL277/CRM
- **Real product UI** — the same repo's `claude/blissful-hawking-47l6fd` branch, `apps/web/` (`landing.html`, `auth.html`, `index.html`). This is the actual shipped CRM web app — a functional dark-themed build. Appu's app + marketing + auth UI kits **recreate these real screens** (their information architecture and content), restyled into the Appu design system.
- **Visual reference** — `uploads/DESIGN-clay.md`, a design analysis of Clay.com's vibrant claymation aesthetic, used as the visual anchor for Appu's brand.

> The brand identity (cream claymation aesthetic, the name "Appu", the warm
> palette) is an original direction anchored on the Clay reference — the real
> product ships a basic dark-blue theme. The UI kits keep the real product's
> screens and IA but re-skin them entirely in the Appu design system.

---

## Content fundamentals

How Appu writes.

- **Voice:** confident, warm, plain-spoken. Short declaratives. The product is the
  hero and it *does things* — lead with verbs: "Builds itself." "Books and signs
  itself." "Knows who to chase."
- **Person:** address the user as **you**; the product/agents are **it / agents /
  the bot** (third person). Never "we" in product UI; "we" is fine in marketing
  body ("we'll never share it").
- **Casing:** sentence case for everything — headlines, buttons, nav, labels.
  UPPERCASE only for tiny eyebrow labels and table headers (12px, 1.5px tracking).
- **Numbers as proof:** concrete metrics over adjectives — "under 60 seconds",
  "+38% vs control", "live in an afternoon". Use real units; mono font for data.
- **Tone of agency:** agentic actions are stated matter-of-factly and always paired
  with trust ("approval-gated", "dry-run first", "every change is audited"). Never
  oversell autonomy without the guardrail.
- **Emoji:** sparing and only inside conversational/bot copy (a single 👋 or ✅ in a
  chat bubble). Never in marketing headlines, nav, or UI chrome.
- **Examples:**
  - Hero: *"The CRM that builds itself."* / *"Describe your business and Appu
    bootstraps your whole CRM."*
  - Button: *Try free* · *Book a demo* · *Build with AI* · *Approve & build*
  - Empty/agent state: *"Agents are working — 3 journeys live, 41 leads in nurture."*
  - Microcopy: *"Bot is replying — type to take over…"*

## Visual foundations

- **Canvas:** warm cream `#fffaf0` (`--vb-canvas`) — non-negotiable. It differentiates
  Appu from cool-gray data tools. Surfaces step warmer, never cooler:
  soft `#faf5e8` → card `#f5f0e0` → strong `#ebe6d6`. Dark teal-black `#0a1a1a`
  is used rarely (the agent status card).
- **Color voltage:** a 6-color saturated feature palette — pink, teal, lavender,
  peach, ochre, cream. **Cycle** them across a page; never repeat one in a row.
  Pink = outbound/speed, teal = enterprise/featured, lavender = AI/ML,
  peach = general warmth, ochre = community/cold-leads.
- **CTAs:** near-black ink `#0a0a0a`, white text, 12px radius, 44px tall. White
  `onColor` buttons over saturated cards.
- **Type:** **Hanken Grotesk** (substitute for Clay's licensed "Plain") — display at
  weight **500** with negative tracking (−1 to −2.5px) at large sizes; body/UI at
  400/500. **JetBrains Mono** for data, scores, timestamps, code. *Never* bolder than
  500 on display — the rounded face carries warmth without weight. Mixing display
  and body roles is a system violation: display for headlines, sans for everything else.
- **Radius:** generous, matched to the type — 6/8 small, **12** buttons + inputs,
  **16** content cards, **24** feature cards, pill for tabs/badges.
- **Elevation:** restrained. Most surfaces are flat or 1px hairline (`#e5e5e5`).
  Depth comes from *color contrast* (cream vs. saturated card), not heavy shadows.
  A soft low-alpha shadow appears only on floating nodes (journey steps, diff cards).
- **Backgrounds & texture:** flat cream fields. The one decorative motif is
  **claymation 3D illustrations** — rounded organic blobs and a mascot/spark. These
  are *commissioned assets*; in this kit they're represented by animated rounded
  brand-color **blob placeholders** (`.blob`) — swap for real renders.
- **Borders:** 1px hairline; inputs thicken the border to ink on focus and add a
  soft 3px focus ring (`--focus-ring`).
- **Transparency & blur:** sticky marketing nav uses `rgba(255,250,240,0.82)` +
  `backdrop-filter: blur(12px)`. Otherwise surfaces are opaque.
- **Animation:** gentle and sparse. Floaty blob drift on the hero (6–9s ease-in-out),
  120–160ms ease transitions on hover/toggle, a springy switch knob. No bounce-heavy
  or attention-grabbing motion on content.
- **Hover / press:** hover = a step-warmer surface fill (transparent → soft → card)
  or subtle opacity; primary buttons darken to `--vb-ink-active`. Press is a tiny
  scale settle. Never invent new hover colors outside the warm ramp.
- **Imagery vibe:** warm, saturated, hand-crafted, playful. No cool/blue gradients,
  no flat corporate vector art, no stock photography defaults.
- **Cards:** feature cards = saturated fill, 24px radius, 32px padding, **no shadow**.
  Content/stat cards = cream or canvas, 16px radius, 1px hairline. Cream cards get a
  hairline instead of a fill-only look.

## Iconography

- **Library:** **Lucide** (consistent 2px round-cap stroke) — the closest match to a
  clean, friendly outline set, loaded from CDN (`lucide@0.468.0` UMD) via the
  `ui_kits/app/Icon.jsx` helper. *Substitution flag:* the source repo shipped no icon
  set, so Lucide was chosen to fit the rounded, warm character. If you have a
  preferred icon family, swap it here.
- **Style rules:** outline (not filled), 2px stroke, sized 14–18px in UI, tinted with
  `currentColor` or a single brand color on accent chips. Icons sit in a soft
  `color-mix(... 16%, white)` rounded-square chip when they need emphasis.
- **Emoji:** only inside bot/chat copy (👋 ✅). Never as UI iconography.
- **Logo:** the **spark** mark (`assets/vibrant-mark.svg`) — a rounded 4-point star in
  pink with a peach inner spark. Pair with the "Appu" wordmark in Hanken Grotesk
  600, −1.4 tracking. Light wordmark for dark/colored surfaces.

---

## Index / manifest

**Root**
- `styles.css` — the single entry point consumers link; `@import`s every token + font file.
- `tokens/` — `colors.css`, `typography.css`, `spacing.css`, `radius.css` (elevation), `fonts.css`.
- `assets/` — `vibrant-mark.svg`, `vibrant-wordmark.svg`, `vibrant-wordmark-light.svg`.
- `guidelines/` — foundation specimen cards (Colors, Type, Spacing, Brand).
- `docs/` — the product PRD (vision, architecture, data model, conversational AI, ML, etc.).
- `SKILL.md` — Agent-Skill manifest for using this system in Claude Code.

**Components** (`window.VibrantDesignSystem_7e2fbe`)
- `components/core/` — `Button`, `Input`, `Badge`, `Avatar`, `Tabs`, `Switch`.
- `components/cards/` — `FeatureCard`, `StatCard`.
  Each has a `.jsx`, `.d.ts` (props), `.prompt.md` (usage), and a directory `@dsCard`.

**UI kits**
- `ui_kits/app/` — the Appu CRM product, recreating the real 8 product tabs:
  **Inbox · Contacts · Cohorts · Pipeline · Analytics · Team · Integrations · Agent harness**, plus `login.html` (auth). `index.html` and `login.html` are Starting Points.
- `ui_kits/marketing/` — the Appu marketing site (hero → 6 feature cards → pricing → cream footer), aligned to the real `landing.html` copy.

## Known gaps & substitutions

- **Fonts:** Clay's "Plain Black" is licensed and unavailable; **Hanken Grotesk** (Google
  Fonts) is the substitute, loaded via `@import` in `tokens/fonts.css` (no local binaries
  shipped). *Want exact brand fonts? Provide the files and I'll swap them in.*
- **Icons:** Lucide substituted (no icon set in the source). Flagged above.
- **Claymation illustrations:** represented by animated CSS blob placeholders — these
  should be replaced with real commissioned 3D renders.
- The UI kits recreate the **real product's screens and IA** (from `apps/web/`),
  re-skinned in Appu — they are cosmetic, not wired to a backend.
