import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { avatarColor, initials as toInitials } from "@/lib/vibrant";

/**
 * Rounded-square initial avatars in the saturated palette, keyed off the
 * person's name so the same face keeps the same colour across screens.
 */
const avatarVariants = cva(
  "inline-flex shrink-0 items-center justify-center overflow-hidden font-semibold text-white select-none",
  {
    variants: {
      size: {
        xs: "size-[22px] rounded-[7px] text-[9px]",
        sm: "size-[28px] rounded-[8px] text-[10px]",
        default: "size-[36px] rounded-[10px] text-xs",
        lg: "size-[48px] rounded-[13px] text-sm",
        xl: "size-16 rounded-[18px] text-2xl font-display",
      },
      shape: {
        square: "",
        circle: "rounded-full",
      },
    },
    defaultVariants: { size: "default", shape: "square" },
  },
);

export interface AvatarProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof avatarVariants> {
  name?: string | null;
  src?: string | null;
  /** Overrides the name-derived colour. */
  color?: string;
}

const Avatar = React.forwardRef<HTMLSpanElement, AvatarProps>(
  ({ className, size, shape, name, src, color, style, ...props }, ref) => {
    const label = toInitials(name);
    return (
      <span
        ref={ref}
        title={name ?? undefined}
        className={cn(avatarVariants({ size, shape }), className)}
        style={{ background: color ?? avatarColor(name ?? "?"), ...style }}
        {...props}
      >
        {src ? (
          <img src={src} alt={name ?? ""} className="size-full object-cover" />
        ) : (
          label
        )}
      </span>
    );
  },
);
Avatar.displayName = "Avatar";

export interface AvatarStackProps extends React.HTMLAttributes<HTMLDivElement> {
  names: (string | null | undefined)[];
  max?: number;
  size?: AvatarProps["size"];
  shape?: AvatarProps["shape"];
}

/** Overlapping row of avatars with a "+n" overflow chip. */
function AvatarStack({
  names,
  max = 4,
  size = "xs",
  shape,
  className,
  ...props
}: AvatarStackProps) {
  const shown = names.slice(0, max);
  const extra = names.length - shown.length;
  return (
    <div className={cn("flex items-center", className)} {...props}>
      {shown.map((name, index) => (
        <Avatar
          key={`${name}-${index}`}
          name={name}
          size={size}
          shape={shape}
          className="-ml-1.5 ring-2 ring-canvas first:ml-0"
        />
      ))}
      {extra > 0 && (
        <span
          className={cn(
            avatarVariants({ size, shape }),
            "-ml-1.5 bg-surface-strong text-muted-ink ring-2 ring-canvas",
          )}
        >
          +{extra}
        </span>
      )}
    </div>
  );
}

export { Avatar, AvatarStack, avatarVariants };
