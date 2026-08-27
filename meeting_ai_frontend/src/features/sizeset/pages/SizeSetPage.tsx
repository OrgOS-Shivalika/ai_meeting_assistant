import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Ruler,
  Upload,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import {
  DOWNLOAD_KINDS,
  DOWNLOAD_LABELS,
  type DownloadKind,
  type SizeSetJob,
  createJob,
  downloadOutput,
  getJob,
  listJobs,
  listStyles,
} from "../api";

// Transcription runs for minutes, so the job is polled rather than awaited.
const POLL_MS = 2500;

const TERMINAL = new Set(["done", "failed"]);

export default function SizeSetPage() {
  const [styles, setStyles] = useState<string[]>([]);
  const [styleNo, setStyleNo] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [jobs, setJobs] = useState<SizeSetJob[]>([]);
  const [active, setActive] = useState<SizeSetJob | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listStyles()
      .then(setStyles)
      .catch((err) => setError(err.message));
    listJobs()
      .then(setJobs)
      .catch(() => {
        // A failing job list must not hide the upload form — the service may
        // simply have restarted and lost its in-memory history.
      });
  }, []);

  // Poll only while a job is unfinished, and stop the moment it terminates.
  useEffect(() => {
    if (!active || TERMINAL.has(active.status)) return;
    const timer = setInterval(async () => {
      try {
        const fresh = await getJob(active.id);
        setActive(fresh);
        setJobs((prev) =>
          prev.map((job) => (job.id === fresh.id ? fresh : job)),
        );
      } catch (err) {
        setError((err as Error).message);
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [active]);

  const submit = useCallback(async () => {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const job = await createJob(file, styleNo);
      setActive(job);
      setJobs((prev) => [job, ...prev]);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  }, [file, styleNo]);

  const save = async (kind: DownloadKind) => {
    if (!active) return;
    try {
      await downloadOutput(active.id, kind);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const busy = active && !TERMINAL.has(active.status);

  return (
    <Layout>
      <PageContainer>
        <PageHeader
          eyebrow="Quality"
          title={
            <span className="flex items-center gap-2">
              <Ruler className="w-5 h-5 text-indigo-600" />
              Size Set Inspection
            </span>
          }
          description="Turn an inspection recording into a filled Size Set report"
        />

        {error && (
          <Card className="mb-6 p-4 border-red-100 bg-red-50 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
            <p className="text-sm font-medium text-red-700">{error}</p>
          </Card>
        )}

        <Card className="p-6 mb-6">
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-2">
                Style
              </label>
              <Select
                value={styleNo}
                onChange={(e) => setStyleNo(e.target.value)}
              >
                <option value="">As announced in the recording</option>
                {styles.map((style) => (
                  <option key={style} value={style}>
                    Style {style}
                  </option>
                ))}
              </Select>
              <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">
                Picks the spec sheet to grade against. Leave it as announced to
                use the style number spoken at the start.
              </p>
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-2">
                Recording
              </label>
              <input
                ref={fileInput}
                type="file"
                accept="audio/*,video/mp4,.m4a,.mp3,.wav,.mp4"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full text-sm text-slate-600 file:mr-3 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
              />
              {file && (
                <p className="text-[11px] text-slate-500 mt-2">
                  {file.name} · {(file.size / 1e6).toFixed(1)} MB
                </p>
              )}
            </div>
          </div>

          <div className="mt-5 flex items-center gap-3">
            <Button onClick={submit} disabled={!file || uploading || !!busy}>
              {uploading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Uploading
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4" /> Generate Size Set
                </>
              )}
            </Button>
            {busy && (
              <span className="text-xs font-medium text-slate-500 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                {active?.message} · {active?.elapsed}s
              </span>
            )}
          </div>
        </Card>

        {active?.status === "failed" && (
          <Card className="p-5 mb-6 border-red-100 bg-red-50">
            <p className="text-sm font-semibold text-red-700 mb-1">
              {active.filename} failed
            </p>
            <p className="text-xs text-red-600">{active.error}</p>
          </Card>
        )}

        {active?.status === "done" && (
          <Card className="p-6 mb-6">
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                  <h3 className="text-base font-semibold text-slate-900">
                    {active.name}
                  </h3>
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  {active.rows} rows · {active.sizes.join(", ")} ·{" "}
                  {active.accessories} accessories · {active.comments} comments
                  · {active.elapsed}s
                </p>
              </div>
              <div
                className={
                  active.flagged
                    ? "shrink-0 px-3 py-1.5 rounded-full bg-amber-50 text-amber-700 text-xs font-semibold"
                    : "shrink-0 px-3 py-1.5 rounded-full bg-emerald-50 text-emerald-700 text-xs font-semibold"
                }
              >
                {active.flagged
                  ? `${active.flagged} need review`
                  : "nothing flagged"}
              </div>
            </div>

            <div className="flex flex-wrap gap-2 mb-5">
              {DOWNLOAD_KINDS.filter((kind) =>
                active.downloads.includes(kind),
              ).map((kind) => (
                <Button
                  key={kind}
                  variant="outline"
                  onClick={() => save(kind)}
                >
                  <Download className="w-3.5 h-3.5" />
                  {DOWNLOAD_LABELS[kind]}
                </Button>
              ))}
            </div>

            {active.flagged_rows.length > 0 && (
              <div className="overflow-x-auto">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  Rows below the confidence threshold
                </p>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-slate-400 border-b border-slate-100">
                      <th className="py-2 pr-3 font-semibold">#</th>
                      <th className="py-2 pr-3 font-semibold">Size</th>
                      <th className="py-2 pr-3 font-semibold">Point</th>
                      <th className="py-2 pr-3 font-semibold">Value</th>
                      <th className="py-2 pr-3 font-semibold">Dev</th>
                      <th className="py-2 pr-3 font-semibold">Conf</th>
                      <th className="py-2 font-semibold">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {active.flagged_rows.map((row) => (
                      <tr
                        key={`${row.no}-${row.size}-${row.field}`}
                        className="border-b border-slate-50 text-slate-700"
                      >
                        <td className="py-2 pr-3 text-slate-400">{row.no}</td>
                        <td className="py-2 pr-3">{row.size}</td>
                        <td className="py-2 pr-3">{row.field}</td>
                        <td className="py-2 pr-3 font-medium">{row.value}</td>
                        <td className="py-2 pr-3">{row.deviation}</td>
                        <td className="py-2 pr-3 text-amber-600 font-semibold">
                          {row.confidence}
                        </td>
                        <td className="py-2 text-slate-500">{row.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Recent
          </p>
          {jobs.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No inspections yet"
              description="Upload a size-set recording to generate its report."
            />
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => (
                <button
                  key={job.id}
                  onClick={() => setActive(job)}
                  className={`w-full text-left p-4 rounded-2xl border-2 transition-colors ${
                    active?.id === job.id
                      ? "border-indigo-600 bg-indigo-50/50"
                      : "border-slate-100 hover:bg-slate-50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-slate-900 truncate">
                      {job.filename}
                    </span>
                    <span className="text-[11px] font-semibold text-slate-400 uppercase shrink-0">
                      {job.status}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">
                    {job.style_no ? `Style ${job.style_no}` : "style as announced"}
                    {job.rows ? ` · ${job.rows} rows` : ""}
                    {job.flagged ? ` · ${job.flagged} to review` : ""}
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>
      </PageContainer>
    </Layout>
  );
}
