/**
 * Citation chip — clickable `[N]` tag that opens a popover with the
 * source preview (meeting title + speakers, or doc filename + section).
 *
 * Clicking the chip itself navigates to the underlying source. The
 * popover is hover-triggered for fast skimming.
 *
 * Phase 6B: every click also fires a beacon to
 *   POST /rag/runs/{runId}/citations/{index}/click
 * which the importance scorer reads as the strongest "this chunk was
 * useful" signal. Non-blocking — beacon failure never disrupts
 * navigation.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, FileText, MessageSquare } from "lucide-react";
import type { CitationDTO } from "../types";
import { apiUrl } from "../../../services/config";

interface Props {
  citation: CitationDTO;
  /** The run that produced this citation. Required to beacon a click;
   * if absent (e.g. a citation rendered outside the chat context) the
   * beacon is silently skipped. */
  runId?: string | null;
}

function beaconClick(runId: string, citationIndex: number): void {
  // Fire-and-forget. `keepalive` ensures the request survives the
  // navigation that follows. Beacon failure must never block UX —
  // we don't await or surface errors.
  const url = apiUrl(`/rag/runs/${runId}/citations/${citationIndex}/click`);
  try {
    fetch(url, {
      method: "POST",
      credentials: "include",
      keepalive: true,
    }).catch(() => {
      /* silent */
    });
  } catch {
    /* silent */
  }
}

export default function CitationChip({ citation, runId }: Props) {
  const [open, setOpen] = useState(false);

  const isDoc = citation.source_type === "document";
  // Deep-link target:
  //   meeting hits  -> /meeting/{id}?chunk={chunk_id}
  //   document hits -> /documents/{kind}/{doc_id}/chunks (Phase 4E
  //                    inspection endpoint; UI not present yet, so we
  //                    fall back to a no-op anchor in that case).
  const href = isDoc
    ? `/documents/${citation.document_kind ?? "category"}/${citation.document_id}/chunks`
    : `/meeting/${citation.meeting_id}?chunk=${citation.chunk_id}`;

  const onClickChip = () => {
    if (runId) beaconClick(runId, citation.index);
  };

  const label = isDoc
    ? citation.document_name ?? "document"
    : citation.meeting_title ?? "meeting";

  const subline = isDoc
    ? [
        citation.section_path ? `§ ${citation.section_path}` : null,
        citation.page_number != null ? `p. ${citation.page_number}` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : null;

  return (
    <span
      className="relative inline-block"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <Link
        to={href}
        onClick={onClickChip}
        className="mx-0.5 inline-flex items-center rounded-full bg-info/12 px-2 py-0.5 align-baseline font-mono text-[10px] font-semibold text-info transition-colors hover:bg-info/20"
      >
        [{citation.index}]
      </Link>
      {open && (
        <span
          role="tooltip"
          className="pointer-events-auto absolute top-full left-0 z-50 mt-1.5 w-72 rounded-lg border border-hairline bg-canvas p-3.5 text-left whitespace-normal shadow-raised"
        >
          <span className="flex items-start gap-2.5">
            {isDoc ? (
              <FileText className="mt-0.5 size-4 shrink-0 text-info" />
            ) : (
              <MessageSquare className="mt-0.5 size-4 shrink-0 text-pink" />
            )}
            <span className="min-w-0 flex-1">
              <span className="vb-label-caps block">
                {isDoc ? "Document" : "Meeting"}
              </span>
              <span className="mt-1 block truncate text-[13px] font-semibold text-ink">
                {label}
              </span>
              {subline && (
                <span className="mt-0.5 block font-mono text-[10px] text-muted-ink">
                  {subline}
                </span>
              )}
              <Link
                to={href}
                onClick={onClickChip}
                className="mt-2.5 inline-flex items-center gap-1 text-[11px] font-semibold text-ink hover:underline"
              >
                Open source <ExternalLink className="size-3" />
              </Link>
            </span>
          </span>
        </span>
      )}
    </span>
  );
}
