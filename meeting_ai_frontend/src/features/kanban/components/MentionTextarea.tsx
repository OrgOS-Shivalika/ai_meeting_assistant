// Comment composer with an `@` picker.
//
// A plain <textarea>, deliberately — a rich-text editor would be a new
// dependency and a rewrite of the composer to gain nothing at this scale
// (the largest org in production has ten people). The mention is inserted as
// literal `@[Name](uuid)` markup into the same string the server already
// stores; `MentionText` renders it back out.
//
// The trigger is the last `@` before the caret with no whitespace after it, so
// an email address mid-sentence doesn't open the picker on every keystroke —
// `a@b` has no space before the `@`, and we require the `@` to start a word.
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchOrgMembers, type OrgMember } from "../api";

// The composer shows `@Divyansh Bhardwaj`; the wire carries
// `@[Divyansh Bhardwaj](uuid)`. Keeping the storage format in the textarea —
// which is what the first version did — made the author stare at a raw uuid
// while typing, which is exactly what a mention feature is supposed to hide.
//
// The parent's contract is unchanged: `value` and `onChange` are still the
// STORAGE form. The display form lives only inside this component.
const STORAGE_RE = /@\[([^\]\n]{1,120})\]\(([0-9a-fA-F-]{36})\)/g;

/** Storage markup -> what the user sees, plus the name->id map behind it. */
export function toDisplay(storage: string): { text: string; map: Map<string, string> } {
  const map = new Map<string, string>();
  STORAGE_RE.lastIndex = 0;
  const text = (storage || "").replace(STORAGE_RE, (_m, name, id) => {
    map.set(name, id);
    return "@" + name;
  });
  return { text, map };
}

/** What the user sees -> storage markup, using only names they actually picked.
 *
 * Longest name first: with both "Divyansh" and "Divyansh Bhardwaj" picked, the
 * short one would otherwise consume the prefix of the long one and leave a
 * dangling " Bhardwaj". A name the user edited after picking simply stops
 * matching and reverts to plain text — it is no longer a mention, which is
 * honest rather than silently pointing at whoever was picked first.
 */
export function toStorage(display: string, map: Map<string, string>): string {
  let out = display || "";
  const names = [...map.keys()].sort((a, b) => b.length - a.length);
  for (const name of names) {
    const id = map.get(name)!;
    out = out.split("@" + name).join(`@[${name}](${id})`);
  }
  return out;
}

interface Props {
  value: string;
  onChange: (next: string) => void;
  onSubmit?: () => void;
  taskId: number;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
  className?: string;
}

/** The `@query` immediately before the caret, or null. */
export function activeMentionQuery(
  text: string,
  caret: number,
): { start: number; query: string } | null {
  const upto = text.slice(0, caret);
  const at = upto.lastIndexOf("@");
  if (at === -1) return null;
  // Must start a word: beginning of input, or preceded by whitespace. Stops
  // "someone@example.com" from opening the picker.
  const before = at === 0 ? "" : upto[at - 1];
  if (before && !/\s/.test(before)) return null;
  const query = upto.slice(at + 1);
  // A completed mention or a new line ends the trigger.
  if (/[\s\]()]/.test(query)) return null;
  return { start: at, query };
}

export default function MentionTextarea({
  value, onChange, onSubmit, taskId,
  placeholder, disabled, rows = 3, className,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  // Display text + the name->id map for mentions the user actually picked.
  // Re-derived when the parent hands us a different body (switching comments,
  // or a reset to "" after posting), NOT on every keystroke — that would undo
  // the user's edits mid-type.
  const [display, setDisplay] = useState(() => toDisplay(value).text);
  const mapRef = useRef<Map<string, string>>(toDisplay(value).map);
  const lastValue = useRef(value);
  useEffect(() => {
    if (value !== lastValue.current && value !== toStorage(display, mapRef.current)) {
      const d = toDisplay(value);
      setDisplay(d.text);
      mapRef.current = d.map;
    }
    lastValue.current = value;
  }, [value, display]);

  const emit = (nextDisplay: string) => {
    setDisplay(nextDisplay);
    const storage = toStorage(nextDisplay, mapRef.current);
    lastValue.current = storage;
    onChange(storage);
  };

  const [members, setMembers] = useState<OrgMember[]>([]);
  const [trigger, setTrigger] = useState<{ start: number; query: string } | null>(null);
  const [highlight, setHighlight] = useState(0);

  // Fetched once per task, lazily — the drawer opens far more often than
  // anyone types an `@`.
  useEffect(() => {
    let alive = true;
    if (trigger && members.length === 0) {
      fetchOrgMembers(taskId)
        .then((m) => alive && setMembers(m))
        .catch(() => alive && setMembers([]));
    }
    return () => { alive = false; };
  }, [trigger, members.length, taskId]);

  const matches = useMemo(() => {
    if (!trigger) return [];
    const q = trigger.query.toLowerCase();
    return members
      .filter((m) => m.name.toLowerCase().includes(q))
      .slice(0, 8);
  }, [trigger, members]);

  const sync = () => {
    const el = ref.current;
    if (!el) return;
    setTrigger(activeMentionQuery(el.value, el.selectionStart ?? 0));
    setHighlight(0);
  };

  const insert = (m: OrgMember) => {
    const el = ref.current;
    if (!el || !trigger) return;
    const caret = el.selectionStart ?? 0;
    // Remember which person this name means, so `toStorage` can turn the
    // plain `@Name` the user sees back into markup on the way out.
    mapRef.current.set(m.name, m.id);
    const inserted = `@${m.name} `;
    const next = display.slice(0, trigger.start) + inserted + display.slice(caret);
    emit(next);
    setTrigger(null);
    // Put the caret after the inserted mention rather than leaving it where
    // the shorter `@query` used to end.
    const pos = trigger.start + inserted.length;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(pos, pos);
    });
  };

  // Clamp: `matches` shrinks as the query narrows, so a highlight index held
  // from a longer list can point past the end — `matches[highlight]` would then
  // be undefined and Enter would insert nothing, which reads as "navigation is
  // broken".
  const active = matches.length ? Math.min(highlight, matches.length - 1) : 0;
  const open = trigger !== null && matches.length > 0;

  return (
    <div className="relative">
      <textarea
        ref={ref}
        value={display}
        rows={rows}
        disabled={disabled}
        placeholder={placeholder}
        className={className}
        onChange={(e) => { emit(e.target.value); sync(); }}
        onClick={sync}
        // No onKeyUp sync: it re-ran `sync()` after every keystroke, and
        // `sync()` resets `highlight` to 0 — so each arrow press moved the
        // selection and then immediately put it back. onChange covers edits;
        // arrows and clicks are handled explicitly below.
        onKeyUp={(e) => {
          if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) sync();
        }}
        onBlur={() => setTimeout(() => setTrigger(null), 120)}
        onKeyDown={(e) => {
          if (open) {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setHighlight((h) => (h + 1) % matches.length);
              return;
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setHighlight((h) => (h - 1 + matches.length) % matches.length);
              return;
            }
            if (e.key === "Enter" || e.key === "Tab") {
              e.preventDefault();
              insert(matches[active]);
              return;
            }
            if (e.key === "Escape") { setTrigger(null); return; }
          }
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") onSubmit?.();
        }}
      />

      {open && (
        <ul className="absolute bottom-full left-0 z-20 mb-1 max-h-56 w-64 overflow-y-auto rounded-md border border-hairline bg-canvas py-1 shadow-raised">
          {matches.map((m, i) => (
            <li key={m.id}>
              <button
                type="button"
                // onMouseDown, not onClick: blur fires first and would close
                // the list before the click ever lands.
                onMouseDown={(e) => { e.preventDefault(); insert(m); }}
                onMouseEnter={() => setHighlight(i)}
                className={`flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-[12px] ${
                  i === active
                    ? "bg-blue-600 text-white"
                    : "hover:bg-blue-50"
                }`}
              >
                <span className="truncate">{m.name}</span>
                {/* Shown rather than hidden: a mention grants nothing, and
                    silently omitting a colleague is more confusing than
                    marking them unreachable. */}
                {m.can_view === false && (
                  <span className={`shrink-0 text-[9px] tracking-wide uppercase ${
                    i === active ? "text-blue-100" : "text-muted-soft"
                  }`}>
                    no access
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
