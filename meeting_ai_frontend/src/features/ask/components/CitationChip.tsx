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
        className="inline-flex items-center align-baseline mx-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-indigo-50 text-indigo-700 border border-indigo-200 hover:bg-indigo-100 transition-colors"
      >
        [{citation.index}]
      </Link>
      {open && (
        <span
          role="tooltip"
          className="absolute z-50 left-0 top-full mt-1 w-72 bg-white shadow-xl border border-slate-200 rounded-lg p-3 text-left whitespace-normal pointer-events-auto"
        >
          <span className="flex items-start gap-2">
            {isDoc ? (
              <FileText className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
            ) : (
              <MessageSquare className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
            )}
            <span className="min-w-0 flex-1">
              <span className="block text-[10px] font-bold uppercase tracking-wider text-slate-400">
                {isDoc ? "Document" : "Meeting"}
              </span>
              <span className="block text-xs font-semibold text-slate-800 truncate">
                {label}
              </span>
              {subline && (
                <span className="block text-[10px] text-slate-500 mt-0.5">
                  {subline}
                </span>
              )}
              <Link
                to={href}
                onClick={onClickChip}
                className="inline-flex items-center gap-1 mt-2 text-[10px] font-bold uppercase tracking-wider text-indigo-600 hover:text-indigo-800"
              >
                Open source <ExternalLink className="w-3 h-3" />
              </Link>
            </span>
          </span>
        </span>
      )}
    </span>
  );
}
