/**
 * Helpers for the Appu / vibrant design language.
 *
 * The design system leans on two moves that are awkward to express as
 * static Tailwind classes: soft `color-mix` tints derived from a brand
 * hue, and cycling the saturated palette across a list so no two
 * adjacent items share a colour. Both live here.
 */

/** The six saturated feature hues, in cycle order. */
export const ACCENTS = [
  "var(--vb-pink)",
  "var(--vb-info)",
  "var(--vb-lavender)",
  "var(--vb-peach)",
  "var(--vb-ochre)",
  "var(--vb-coral)",
] as const;

/** Semantic hues, for status rather than decoration. */
export const SEMANTIC = {
  success: "var(--vb-success)",
  warning: "var(--vb-warning)",
  error: "var(--vb-error)",
  info: "var(--vb-info)",
} as const;

/**
 * A soft wash of `color` over white — the fill behind icon chips and
 * status pills. 12% is the system default; pills on warning use 14%.
 */
export function tint(color: string, pct = 12): string {
  return `color-mix(in srgb, ${color} ${pct}%, white)`;
}

/** Cycles the feature palette so adjacent items never repeat a hue. */
export function accent(index: number): string {
  return ACCENTS[index % ACCENTS.length];
}

/**
 * Stable per-person colour so the same name always gets the same avatar
 * across screens. A name is the only identifier some participants have.
 */
export function avatarColor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  }
  return ACCENTS[Math.abs(hash) % ACCENTS.length];
}

/** "Ada Lovelace" -> "AL"; "dana@acme.com" -> "DA". */
export function initials(name?: string | null, fallback = "?"): string {
  const source = (name ?? "").trim();
  if (!source) return fallback;
  const words = source.split(/[\s._-]+/).filter(Boolean);
  if (words.length === 0) return fallback;
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

/** Inline style for an icon chip: soft tint fill, brand-coloured glyph. */
export function chipStyle(color: string, pct = 12) {
  return { background: tint(color, pct), color };
}
