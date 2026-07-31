import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Primary action is near-black ink, 12px radius, 44px tall. `onColor` is
 * the white button used on top of a saturated feature card. Hover moves a
 * step warmer along the cream ramp — never to a new hue.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-all duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ink/25 disabled:pointer-events-none disabled:opacity-50 active:scale-[0.985] [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-ink text-on-ink hover:bg-ink-active",
        secondary: "bg-surface-card text-ink hover:bg-surface-strong",
        outline:
          "border border-hairline bg-canvas text-body font-semibold hover:bg-surface-soft hover:text-ink",
        ghost: "text-muted-ink hover:bg-surface-card hover:text-ink",
        // Pure white on purpose: this variant sits on a saturated card,
        // where cream would read as a smudge.
        onColor: "bg-white text-ink hover:bg-white/90",
        destructive: "bg-error text-white hover:bg-error/90",
        destructiveOutline:
          "border border-hairline bg-transparent text-error font-semibold hover:bg-error/10",
        link: "text-ink underline-offset-4 hover:underline",
      },
      size: {
        default: "h-11 px-[18px] text-sm [&_svg]:size-4",
        sm: "h-[38px] px-[15px] text-[13px] [&_svg]:size-3.5",
        xs: "h-8 px-3 rounded-sm text-xs [&_svg]:size-3.5",
        lg: "h-12 px-6 text-[15px] [&_svg]:size-[18px]",
        icon: "size-11 [&_svg]:size-[18px]",
        iconSm: "size-[38px] rounded-md [&_svg]:size-4",
        pill: "h-9 px-4 rounded-full text-[13px] [&_svg]:size-3.5",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
