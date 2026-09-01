// Renders a comment body, turning `@[Name](uuid)` into a chip.
//
// The name is read from the STORED text, not looked up — the server snapshots
// it into the body at save time (and rewrites it from the database, so it is
// the real name rather than whatever the client typed). That is what makes a
// mention still render correctly after the person is renamed or deleted.
//
// Split with a capturing regex so the plain text between mentions survives
// verbatim; the body is inserted as text nodes throughout, never as HTML.
const MENTION_RE = /@\[([^\]\n]{1,120})\]\(([0-9a-fA-F-]{36})\)/g;

export default function MentionText({ body }: { body: string }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;

  // `exec` in a loop needs a fresh lastIndex — the regex is module-level and
  // /g regexes carry state between calls.
  MENTION_RE.lastIndex = 0;
  while ((match = MENTION_RE.exec(body)) !== null) {
    if (match.index > last) parts.push(body.slice(last, match.index));
    parts.push(
      <span
        key={`${match.index}-${match[2]}`}
        className="rounded-xs bg-blue-100 px-1 py-0.5 font-semibold text-blue-700"
      >
        @{match[1]}
      </span>,
    );
    last = match.index + match[0].length;
  }
  if (last < body.length) parts.push(body.slice(last));

  return <>{parts}</>;
}
