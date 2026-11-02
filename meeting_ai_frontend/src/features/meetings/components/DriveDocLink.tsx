// "Open in Drive" on the transcript header — shown only once this meeting's
// Doc exists in the current user's Google Drive (see drive_export_service).
import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { apiClient } from "../../../services/apiClient";

export default function DriveDocLink({ meetingId }: { meetingId: number }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    apiClient(`/auth/google/drive/meeting/${meetingId}`)
      .then((d) => setUrl(d?.url ?? null))
      .catch(() => setUrl(null));
  }, [meetingId]);

  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-indigo-600 hover:text-indigo-700 px-1.5 py-0.5 hover:bg-indigo-50 rounded"
      title="Open this meeting's transcript Doc in Google Drive"
    >
      <ExternalLink className="w-2.5 h-2.5" />
      Open in Drive
    </a>
  );
}
