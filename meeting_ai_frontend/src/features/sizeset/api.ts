// Size Set inspection reports. Every call goes through the backend proxy at
// /api/sizeset, never straight to the sizeset service — it has no auth of its
// own and no CORS headers, so the browser must not talk to it directly.
import { apiClient } from "../../services/apiClient";
import { apiUrl } from "../../services/config";

export type JobStatus = "queued" | "running" | "done" | "failed";

export interface FlaggedRow {
  no: number;
  size: string;
  field: string;
  value: string;
  deviation: string;
  confidence: number;
  note: string;
}

export interface SizeSetJob {
  id: string;
  filename: string;
  style_no: string;
  status: JobStatus;
  message: string;
  name: string;
  rows: number;
  flagged: number;
  sizes: string[];
  error: string;
  downloads: DownloadKind[];
  form: Record<string, string>;
  accessories: number;
  comments: number;
  flagged_rows: FlaggedRow[];
  elapsed: number;
}

export const DOWNLOAD_KINDS = ["report", "form", "measurements", "data"] as const;
export type DownloadKind = (typeof DOWNLOAD_KINDS)[number];

export const DOWNLOAD_LABELS: Record<DownloadKind, string> = {
  report: "Report (PDF)",
  form: "Filled form (CSV)",
  measurements: "Measurements (CSV)",
  data: "Raw data (JSON)",
};

export const listStyles = (): Promise<string[]> => apiClient("/sizeset/styles");

// Which category may produce Size Set reports. Server-side configuration, so
// the SPA asks rather than assuming.
export const readConfig = (): Promise<{ category_name: string }> =>
  apiClient("/sizeset/config");

// Option A — build the report from a meeting's own transcript instead of an
// uploaded recording.
export const createJobFromMeeting = (
  meetingId: number,
  styleNo: string,
): Promise<SizeSetJob> =>
  apiClient(`/sizeset/from-meeting/${meetingId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ style_no: styleNo }),
  });

export const listJobs = (): Promise<SizeSetJob[]> => apiClient("/sizeset/jobs");

export const getJob = (id: string): Promise<SizeSetJob> =>
  apiClient(`/sizeset/jobs/${id}`);

// Multipart, so raw fetch rather than apiClient: the browser has to set
// Content-Type itself to include the multipart boundary. Same approach as
// DocumentsPanel's upload.
export async function createJob(
  file: File,
  styleNo: string,
): Promise<SizeSetJob> {
  const form = new FormData();
  form.append("recording", file);
  form.append("style_no", styleNo);

  const res = await fetch(apiUrl("/sizeset/jobs"), {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    let detail = `Upload failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // non-JSON error body — keep the generic message
    }
    throw new Error(detail);
  }
  return res.json();
}

/**
 * Download one output.
 *
 * Fetched as a blob and saved via an object URL rather than pointing an <a> at
 * the endpoint. A plain link navigation sends `Accept: text/html`, and the
 * backend's SPA-shell middleware intercepts ANY such GET outside a small
 * passthrough set — so a direct link would hand back index.html instead of the
 * PDF. fetch() sends `Accept: *​/*` and is unaffected.
 */
export async function downloadOutput(
  jobId: string,
  kind: DownloadKind,
): Promise<void> {
  const res = await fetch(apiUrl(`/sizeset/jobs/${jobId}/download/${kind}`), {
    credentials: "include",
  });
  if (!res.ok) {
    let detail = `Download failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // non-JSON error body — keep the generic message
    }
    throw new Error(detail);
  }

  // Prefer the filename the service chose; it carries the report's version
  // suffix, e.g. "rec 2365(2).pdf".
  const disposition = res.headers.get("content-disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const filename = match ? decodeURIComponent(match[1]) : `${jobId}-${kind}`;

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
