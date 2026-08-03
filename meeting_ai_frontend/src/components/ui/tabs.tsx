import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Underline tabs — the system's section switcher (Meeting detail, Board,
 * Settings, Agents). Active is ink text over a 2px ink rule.
 *
 * Same surface as the shadcn Tabs primitive (`value` / `onValueChange` /
 * `TabsContent`), hand-rolled because the Radix tabs package isn't
 * vendored in this project.
 */

type TabsContextValue = {
  value: string;
  setValue: (value: string) => void;
};

const TabsContext = React.createContext<TabsContextValue | null>(null);

function useTabs(component: string) {
  const ctx = React.useContext(TabsContext);
  if (!ctx) throw new Error(`<${component}> must be used inside <Tabs>`);
  return ctx;
}

export interface TabsProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
}

function Tabs({
  value,
  defaultValue,
  onValueChange,
  className,
  children,
  ...props
}: TabsProps) {
  const [uncontrolled, setUncontrolled] = React.useState(defaultValue ?? "");
  const current = value ?? uncontrolled;

  const setValue = React.useCallback(
    (next: string) => {
      if (value === undefined) setUncontrolled(next);
      onValueChange?.(next);
    },
    [value, onValueChange],
  );

  const ctx = React.useMemo(
    () => ({ value: current, setValue }),
    [current, setValue],
  );

  return (
    <TabsContext.Provider value={ctx}>
      <div className={className} {...props}>
        {children}
      </div>
    </TabsContext.Provider>
  );
}

const TabsList = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    role="tablist"
    className={cn(
      "flex items-center gap-6 overflow-x-auto border-b border-hairline vb-no-scrollbar",
      className,
    )}
    {...props}
  />
));
TabsList.displayName = "TabsList";

export interface TabsTriggerProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string;
  /** Optional count rendered as a soft pill after the label. */
  count?: number | string;
}

const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ className, value, count, children, onClick, ...props }, ref) => {
    const { value: active, setValue } = useTabs("TabsTrigger");
    const selected = active === value;
    return (
      <button
        ref={ref}
        type="button"
        role="tab"
        aria-selected={selected}
        onClick={(event) => {
          setValue(value);
          onClick?.(event);
        }}
        className={cn(
          "-mb-px flex shrink-0 items-center gap-2 border-b-2 px-0.5 py-2.5 text-sm transition-colors",
          selected
            ? "border-ink font-semibold text-ink"
            : "border-transparent font-medium text-muted-ink hover:text-body-strong",
          className,
        )}
        {...props}
      >
        {children}
        {count !== undefined && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[11px] font-semibold",
              selected ? "bg-surface-card text-ink" : "bg-surface-soft text-muted-ink",
            )}
          >
            {count}
          </span>
        )}
      </button>
    );
  },
);
TabsTrigger.displayName = "TabsTrigger";

export interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string;
}

const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  ({ className, value, children, ...props }, ref) => {
    const { value: active } = useTabs("TabsContent");
    if (active !== value) return null;
    return (
      <div ref={ref} role="tabpanel" className={className} {...props}>
        {children}
      </div>
    );
  },
);
TabsContent.displayName = "TabsContent";

export { Tabs, TabsList, TabsTrigger, TabsContent };
