import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { tint } from "@/lib/vibrant";

/**
 * The soft rounded-square an icon sits in when it needs emphasis — a 16%
 * (default 12%) wash of the accent hue over white, glyph in the hue itself.
 */
const iconChipVariants = cva(
  "inline-flex shrink-0 items-center justify-center [&_svg]:shrink-0",
  {
    variants: {
      size: {
        sm: "size-8 rounded-[9px] [&_svg]:size-4",
        default: "size-[38px] rounded-[11px] [&_svg]:size-[17px]",
        lg: "size-11 rounded-[12px] [&_svg]:size-5",
        xl: "size-13 rounded-[16px] [&_svg]:size-6",
      },
    },
    defaultVariants: { size: "default" },
  },
);

export interface IconChipProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof iconChipVariants> {
  /** Any CSS colour — usually a `var(--vb-*)` brand token. */
  color?: string;
  /** Tint strength of the fill, in percent. */
  strength?: number;
  /** Fill solid with `color` and render the glyph in white instead. */
  solid?: boolean;
}

const IconChip = React.forwardRef<HTMLSpanElement, IconChipProps>(
  (
    { className, size, color = "var(--vb-info)", strength = 12, solid, style, ...props },
    ref,
  ) => (
    <span
      ref={ref}
      className={cn(iconChipVariants({ size }), className)}
      style={
        solid
          ? { background: color, color: "#fff", ...style }
          : { background: tint(color, strength), color, ...style }
      }
      {...props}
    />
  ),
);
IconChip.displayName = "IconChip";

export { IconChip, iconChipVariants };
