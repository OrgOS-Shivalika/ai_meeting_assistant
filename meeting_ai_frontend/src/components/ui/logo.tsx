import mark from "@/assets/brand/imagine-mark.svg";
import lockupDark from "@/assets/brand/imagine-lockup-dark.png";
import lockupLight from "@/assets/brand/imagine-lockup-light.png";
import { cn } from "@/lib/utils";

/**
 * The imagine.bo brand marks.
 *
 * `mark` is the standalone chevron — SVG, so it stays crisp at any size and
 * is the right choice anywhere the wordmark would be too small to read.
 * `lockup` is mark + wordmark. That one is a raster asset because the
 * wordmark's typeface isn't among the fonts this app loads, so the PNG is
 * what preserves the letterforms.
 *
 * `tone` selects the wordmark colour, NOT the mark: use "dark" on the cream
 * canvas and "light" on the ink panels. The gradient chevron is identical in
 * both, so only the type changes.
 */
export interface LogoProps
  extends Omit<React.ImgHTMLAttributes<HTMLImageElement>, "src" | "alt"> {
  variant?: "mark" | "lockup";
  tone?: "dark" | "light";
  /** Defaults to the brand name; pass "" when the logo is decorative. */
  alt?: string;
}

/**
 * Does `value` name the imagine.bo brand?
 *
 * Guards the places where the mark accompanies user data (category names,
 * team names) so it appears only for the brand itself and not beside every
 * label. Punctuation and case are ignored, because the same name gets typed
 * as "imagine.bo", "Imaginebo" and "Imagine BO" — all of which are it.
 */
const BRAND_SLUG = "imaginebo";

export function isBrandName(value?: string | null): boolean {
  if (!value) return false;
  return value.toLowerCase().replace(/[^a-z0-9]/g, "") === BRAND_SLUG;
}

export function Logo({
  variant = "lockup",
  tone = "dark",
  className,
  alt,
  ...props
}: LogoProps) {
  const src =
    variant === "mark" ? mark : tone === "light" ? lockupLight : lockupDark;

  return (
    <img
      src={src}
      alt={alt ?? "imagine.bo"}
      // Height-driven: both assets are wider than they are tall (the mark
      // being the taller ratio), so callers set a height and let the width
      // follow rather than risk squashing either one.
      className={cn(
        "w-auto shrink-0 select-none",
        variant === "mark" ? "h-8" : "h-7",
        className,
      )}
      draggable={false}
      {...props}
    />
  );
}
