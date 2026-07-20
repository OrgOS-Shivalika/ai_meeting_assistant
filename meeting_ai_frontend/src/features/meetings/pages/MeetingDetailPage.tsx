import { Link, useParams } from "react-router-dom";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { fetchMeetingById, updateMeeting, updateTask } from "../api";
import { apiClient } from "../../../services/apiClient";
import Layout from "../../../shared/components/Layout";
import { Skeleton, SkeletonCard, SkeletonText } from "../../../shared/components/Skeleton";
import CategoryAssignControl from "../components/CategoryAssignControl";
import TaskAssignmentEditor from "../components/TaskAssignmentEditor";
import AskAssistantPanel from "../components/AskAssistantPanel";
import MeetingBoardLink from "../../kanban/components/MeetingBoardLink";
import {
  Calendar,
  Clock,
  Users,
  Sparkles,
  Share2,
  Download,
  ExternalLink,
  ChevronLeft,
  AlertCircle,
  CheckCircle2,
  Inbox,
  Pencil,
  Radio,
  Zap,
} from "lucide-react";
import type { Meeting, Participant, Task } from "../types";
import MeetingAIMemorySection from "../components/MeetingAIMemorySection";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  useLiveTranscript,
  type LiveFinal,
} from "../hooks/useLiveTranscript";

type TaskOverride = Partial<Omit<Task, "owner">> & {
  owner?: string | null;
};

type AgentInsight = {
  id: number;
  agent_id: number;
  agent_slug: string;
  agent_name: string;
  prompt_key: string;
  prompt_version: number | null;
  // Shape depends on prompt_key — dispatched in AgentInsightCard.
  // Kept as `any` here since the concrete shape belongs to each
  // skill's renderer, not the fetch call.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: any;
  created_at_iso: string;
};

type TranscriptGroup = {
  speaker: string;
  timestamp?: number | string;
  messages: string[];
  isPartial?: boolean;
};

const getInitials = (name: string) => {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
};

const AVATAR_COLORS = [
  "bg-indigo-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-violet-500",
  "bg-pink-500",
  "bg-cyan-500",
  "bg-orange-500",
  "bg-teal-500",
  "bg-fuchsia-500",
];
const colorFor = (name: string) => {
  let hash = 0;
  for (let i = 0; i < name.length; i++)
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
};

const formatTime = (ts?: number | string) => {
  if (!ts && ts !== 0) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
};

const formatDate = (iso?: string | null) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const formatDateShort = (iso?: string | null) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

const computeDuration = (m: Meeting): string | null => {
  if (m.duration_minutes != null && m.duration_minutes > 0) {
    return `${m.duration_minutes} min`;
  }
  if (m.started_at && m.ended_at) {
    const diff =
      (new Date(m.ended_at).getTime() - new Date(m.started_at).getTime()) /
      60000;
    if (diff > 0) return `${Math.round(diff)} min`;
  }
  return null;
};

const PRIORITY_STYLE: Record<string, string> = {
  high: "bg-red-50 text-red-700",
  medium: "bg-amber-50 text-amber-700",
  low: "bg-slate-100 text-slate-600",
};

const parseStoredTranscript = (blob: string): LiveFinal[] => {
  return blob
    .split("\n")
    .filter((l) => l.trim())
    .map((line) => {
      const colonIdx = line.indexOf(": ");
      const speaker = colonIdx >= 0 ? line.slice(0, colonIdx) : "Unknown";
      const text = colonIdx >= 0 ? line.slice(colonIdx + 2) : line;
      return { speaker, text, timestamp: Date.now() };
    });
};

export default function MeetingDetailPage() {
  const { id } = useParams();
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [isSavingTitle, setIsSavingTitle] = useState(false);
  const titleInputRef = useRef<HTMLInputElement | null>(null);

  const commitTitle = useCallback(async () => {
    if (!meeting) return;
    const next = titleDraft.trim();
    // Empty or unchanged → cancel silently.
    if (!next || next === (meeting.title || "").trim()) {
      setIsEditingTitle(false);
      return;
    }
    setIsSavingTitle(true);
    try {
      const updated = await updateMeeting(meeting.id, { title: next });
      setMeeting((prev) => (prev ? { ...prev, title: updated.title } : prev));
      setIsEditingTitle(false);
    } catch (err) {
      console.error("Failed to rename meeting", err);
      // Leave editor open on failure so user can retry.
    } finally {
      setIsSavingTitle(false);
    }
  }, [meeting, titleDraft]);
  const [error, setError] = useState<string | null>(null);
  // const [aiHighlightsOn, setAiHighlightsOn] = useState(false);
  
  const [activeNotification, setActiveNotification] = useState<any | null>(null);
  const [liveTasks, setLiveTasks] = useState<Task[]>([]);
  // Task assignment edit state. The card is otherwise read-only; opening
  // the editor for a task swaps the owner+date row for the inline
  // TaskAssignmentEditor. Only ONE task editable at a time.
  const [editingTaskId, setEditingTaskId] = useState<number | null>(null);
  const [savingTaskId, setSavingTaskId] = useState<number | null>(null);
  const [taskOverrides, setTaskOverrides] = useState<Record<number, TaskOverride>>({});
  // Memory Phase 2 — in-meeting AskAssistantPanel state. Closed by default
  // so the meeting content (transcript, tasks) gets the full visual focus.
  // Cmd+K toggles, ? opens, Esc closes (wired inside the panel).
  const [askPanelOpen, setAskPanelOpen] = useState(false);
  const [agentInsights, setAgentInsights] = useState<AgentInsight[]>([]);
  const notificationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const transcriptContainerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  const handleTranscriptScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
    const atBottom = Math.abs(scrollHeight - clientHeight - scrollTop) < 100;
    isNearBottomRef.current = atBottom;
  }, []);

  const refetchMeeting = useCallback(() => {
    if (!id) return;
    fetchMeetingById(id)
      .then((data) => {
        if (data?.id) setMeeting(data);
      })
      .catch((err) => console.error("Refetch failed", err));
  }, [id]);

  const { finals, partial, connected, seed } = useLiveTranscript(
    meeting?.id ?? null,
    {
      onStatusUpdate: (status) => {
        if (
          status === "completed" ||
          status === "failed" ||
          status === "processing"
        ) {
          refetchMeeting();
        }
      },
      onCognitiveEvent: (event) => {
        console.log("🧠 Live Cognitive Event:", event);
        if (event.event_type === "task.created" || event.event_type === "task.updated") {
           setActiveNotification(event);
           if (notificationTimerRef.current) clearTimeout(notificationTimerRef.current);
           notificationTimerRef.current = setTimeout(() => {
             setActiveNotification(null);
           }, 6000);

           const payload = event.payload;
           const newTask: Task = {
             id: payload.id as any,
             task: payload.task,
             owner: payload.owner || "Unassigned",
             priority: "medium",
             due_date: payload.due_date || payload.deadline || null,
             is_completed: payload.status === "completed",
             created_at: payload.source_timestamp,
             updated_at: payload.source_timestamp,
             meeting_id: Number(id)
           };

           setLiveTasks(prev => {
             const exists = prev.findIndex(t => String(t.id) === String(newTask.id));
             if (exists !== -1) {
               const updated = [...prev];
               updated[exists] = newTask;
               return updated;
             }
             return [...prev, newTask];
           });
        }
      },
    },
  );

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    fetchMeetingById(id)
      .then((data) => {
        if (cancelled) return;
        if (data?.error || !data?.id) {
          setError(data?.error || "Meeting not found");
          return;
        }
        setMeeting(data);
      })
      .catch((err) => {
        console.error("Failed to load meeting", err);
        if (!cancelled) setError("Failed to load meeting.");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!meeting?.transcript) return;
    seed(parseStoredTranscript(meeting.transcript));
  }, [meeting?.transcript, seed]);

  // Agent insights (agents_v2). Empty for legacy-pipeline meetings.
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    apiClient(`/agents_v2/meetings/${id}/insights`)
      .then((rows) => { if (!cancelled) setAgentInsights(rows as AgentInsight[]); })
      .catch((err) => console.warn("Agent insights unavailable:", err));
    return () => { cancelled = true; };
  }, [id]);

  useEffect(() => {
    const container = transcriptContainerRef.current;
    if (container && isNearBottomRef.current) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: "smooth"
      });
    }
  }, [finals, partial]);

  const groups = useMemo<TranscriptGroup[]>(() => {
    if (!meeting) return [];
    if (meeting.status === "completed" && meeting.transcript_raw) {
      const raw = meeting.transcript_raw as any[];
      const gs: TranscriptGroup[] = [];
      for (const item of raw) {
        const speaker = item.participant?.name || "Unknown";
        const text = (item.words || []).map((w: any) => w.text).join(" ");
        const ts = item.words?.[0]?.start_timestamp?.absolute;
        const last = gs[gs.length - 1];
        if (last && last.speaker === speaker) {
          last.messages.push(text);
        } else {
          gs.push({ speaker, timestamp: ts, messages: [text] });
        }
      }
      return gs;
    }

    if (finals.length === 0 && !partial) return [];

    const gs: TranscriptGroup[] = [];
    for (const line of finals) {
      const last = gs[gs.length - 1];
      if (last && last.speaker === line.speaker && !last.isPartial) {
        last.messages.push(line.text);
      } else {
        gs.push({
          speaker: line.speaker,
          timestamp: line.timestamp,
          messages: [line.text],
        });
      }
    }
    if (partial) {
      gs.push({
        speaker: partial.speaker,
        messages: [partial.text],
        isPartial: true,
      });
    }
    return gs;
  }, [meeting, finals, partial]);

  const summaryBullets = useMemo(() => {
    if (!meeting?.summary) return [];
    return meeting.summary
      .split(/\n+/)
      .map((line) => line.replace(/^[\s\-•*\d.)]+/, "").trim())
      .filter((line) => line.length > 0)
      .slice(0, 6);
  }, [meeting?.summary]);

  const tasks = useMemo(() => {
    if (!meeting) return [];
    const base = meeting.tasks ?? [];
    const fresh = liveTasks.filter(lt => !base.some(bt => String(bt.id) === String(lt.id)));
    const merged = [...base, ...fresh];
    // Apply local edits over server data so saving feels instant — the
    // server response is also merged into overrides on success.
    return merged.map((t) => {
      const override = taskOverrides[t.id as number];
      return override ? { ...t, ...override } : t;
    });
  }, [meeting, liveTasks, taskOverrides]);

  // Save handler — single PATCH for owner + due date. Optimistically
  // applies the change locally so the row updates before the server
  // round-trip completes.
  const saveTaskAssignment = useCallback(
    async (
      taskId: number,
      next: { owner_name: string | null; due_date: string | null },
    ) => {
      setSavingTaskId(taskId);
      setTaskOverrides((prev) => ({
        ...prev,
        [taskId]: {
          ...(prev[taskId] || {}),
          owner: next.owner_name,
          due_date: next.due_date,
        },
      }));
      try {
        const updated = await updateTask(taskId, next);
        setTaskOverrides((prev) => ({ ...prev, [taskId]: { ...updated } }));
        setEditingTaskId(null);
      } catch (e) {
        console.error("Failed to update task", e);
        // Roll back optimistic update on failure.
        setTaskOverrides((prev) => {
          const copy = { ...prev };
          delete copy[taskId];
          return copy;
        });
      } finally {
        setSavingTaskId(null);
      }
    },
    [],
  );

  if (error) {
    return (
      <Layout>
        <div className="max-w-md mx-auto px-8 py-16">
          <div className="bg-white rounded-lg border border-slate-200 p-10 text-center">
            <div className="w-10 h-10 rounded-md bg-red-50 flex items-center justify-center mx-auto mb-3">
              <AlertCircle className="w-5 h-5 text-red-500" />
            </div>
            <h2 className="text-base font-semibold text-slate-900 mb-1">
              Couldn't load meeting
            </h2>
            <p className="text-sm text-slate-500 mb-5">{error}</p>
            <Button asChild size="sm" className="bg-slate-900 hover:bg-slate-800">
              <Link to="/">
                <ChevronLeft className="w-4 h-4" />
                Back to meetings
              </Link>
            </Button>
          </div>
        </div>
      </Layout>
    );
  }

  if (!meeting) {
    return (
      <Layout>
        <div className="h-full flex flex-col">
          <div className="px-8 py-3 border-b border-slate-200 shrink-0">
            <Skeleton className="h-3 w-64" />
          </div>
          <div className="px-8 py-6 border-b border-slate-200 shrink-0 space-y-3">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-8 w-96" />
            <Skeleton className="h-4 w-64" />
          </div>
          <div className="flex-1 bg-slate-50 p-6 grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-4 min-h-0">
            <div className="bg-white rounded-lg border border-slate-200 p-5">
              <SkeletonText lines={8} />
            </div>
            <div className="space-y-4">
              <SkeletonCard className="h-40" />
              <SkeletonCard className="h-56" />
              <SkeletonCard className="h-32" />
            </div>
          </div>
        </div>
      </Layout>
    );
  }

  const title = meeting.title?.trim() || "Untitled meeting";
  const dateStr = formatDate(meeting.scheduled_at || meeting.started_at || meeting.created_at) || "—";
  const durationStr = computeDuration(meeting);
  const participants: Participant[] = meeting.participants ?? [];
  const taskCount = tasks.length;
  const completedTaskCount = tasks.filter((t) => t.is_completed).length;
  const isTaskUnassigned = (t: Task) => {
    const owner = (t.owner || "").trim().toLowerCase();
    return ["", "tbd", "unassigned", "unknown", "n/a"].includes(owner);
  };
  const unassignedTaskCount = tasks.filter(isTaskUnassigned).length;

  return (
    <Layout>
      <div
        className="h-full flex flex-col"
        style={{
          background: "var(--vb-canvas)",
          fontFamily: "var(--vb-font-sans)",
          color: "var(--vb-body)",
        }}
      >
        {/* Breadcrumb strip */}
        <div
          className="px-8 py-3 flex items-center justify-between shrink-0"
          style={{ borderBottom: "1px solid var(--vb-hairline)" }}
        >
          <div
            className="flex items-center gap-1.5 min-w-0"
            style={{ fontSize: 12, color: "var(--vb-muted)" }}
          >
            <Link
              to="/"
              className="transition-colors"
              onMouseEnter={(e) => (e.currentTarget.style.color = "var(--vb-ink)")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "var(--vb-muted)")}
            >
              Meetings
            </Link>
            {meeting.category && (
              <>
                <span style={{ color: "var(--vb-hairline)" }}>/</span>
                <Link
                  to={`/?category_id=${meeting.category.id}`}
                  className="transition-colors"
                  style={{ color: meeting.category.color || undefined }}
                >
                  {meeting.category.name}
                </Link>
              </>
            )}
            <span style={{ color: "var(--vb-hairline)" }}>/</span>
            <span
              className="truncate"
              style={{ color: "var(--vb-body-strong)", fontWeight: 500 }}
            >
              {title}
            </span>
          </div>
          <div className="shrink-0">
            <CategoryAssignControl
              meetingId={meeting.id}
              category={meeting.category}
              team={meeting.team}
              onChange={({ category, team }) =>
                setMeeting((prev) => (prev ? { ...prev, category, team } : prev))
              }
            />
          </div>
        </div>

        {/* Header strip */}
        <div
          className="px-8 py-6 flex flex-col lg:flex-row lg:items-end justify-between gap-4 shrink-0"
          style={{
            background: "var(--vb-canvas)",
            borderBottom: "1px solid var(--vb-hairline)",
          }}
        >
          <div className="space-y-3 min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <VbStatusPill status={meeting.status} />
              {meeting.meeting_platform && (
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: "0.3px",
                    padding: "4px 9px",
                    borderRadius: 9999,
                    background: "var(--vb-surface-card)",
                    color: "var(--vb-muted)",
                  }}
                >
                  {meeting.meeting_platform.replace(/_/g, " ")}
                </span>
              )}
              {connected && (
                <span
                  className="inline-flex items-center gap-1.5"
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: "4px 9px",
                    borderRadius: 9999,
                    color: "var(--vb-success)",
                    background: "color-mix(in srgb, var(--vb-success) 12%, white)",
                  }}
                >
                  <Radio className="w-2.5 h-2.5" /> Live
                </span>
              )}
            </div>
            {isEditingTitle ? (
              <input
                ref={titleInputRef}
                type="text"
                value={titleDraft}
                disabled={isSavingTitle}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={commitTitle}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitTitle();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    setIsEditingTitle(false);
                  }
                }}
                autoFocus
                maxLength={200}
                style={{
                  fontFamily: "var(--vb-font-display)",
                  fontWeight: 500,
                  fontSize: 32,
                  letterSpacing: "-1px",
                  lineHeight: 1.15,
                  color: "var(--vb-ink)",
                  background: "var(--vb-canvas)",
                  border: "1px solid var(--vb-ink)",
                  borderRadius: 12,
                  boxShadow: "0 0 0 3px var(--focus-ring)",
                  padding: "6px 10px",
                  outline: "none",
                  width: "100%",
                  maxWidth: "42rem",
                }}
              />
            ) : (
              <h1
                className="group inline-flex items-center gap-2 cursor-text"
                onClick={() => {
                  setTitleDraft(meeting.title || "");
                  setIsEditingTitle(true);
                }}
                title="Click to rename"
                style={{
                  fontFamily: "var(--vb-font-display)",
                  fontWeight: 500,
                  fontSize: 32,
                  letterSpacing: "-1px",
                  lineHeight: 1.15,
                  color: "var(--vb-ink)",
                  margin: 0,
                }}
              >
                <span>{title}</span>
                <Pencil
                  className="transition-colors group-hover:text-slate-500"
                  style={{ width: 14, height: 14, color: "var(--vb-muted-soft)" }}
                />
              </h1>
            )}
            <div
              className="flex items-center flex-wrap"
              style={{
                gap: 16,
                fontSize: 13,
                color: "var(--vb-muted)",
                marginTop: 12,
              }}
            >
              <span className="inline-flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5" style={{ color: "var(--vb-muted-soft)" }} />
                {dateStr}
              </span>
              {durationStr && (
                <span className="inline-flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" style={{ color: "var(--vb-muted-soft)" }} />
                  {durationStr}
                </span>
              )}
              <span className="inline-flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5" style={{ color: "var(--vb-muted-soft)" }} />
                {participants.length} participant
                {participants.length === 1 ? "" : "s"}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {meeting.meeting_url && (
              <a
                href={meeting.meeting_url}
                target="_blank"
                rel="noreferrer"
                style={vbSecondaryBtnStyle}
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Open call
              </a>
            )}
            <button
              disabled={!meeting.summary}
              onClick={() =>
                meeting.summary &&
                navigator.clipboard?.writeText(meeting.summary)
              }
              style={{
                ...vbSecondaryBtnStyle,
                opacity: meeting.summary ? 1 : 0.5,
                cursor: meeting.summary ? "pointer" : "not-allowed",
              }}
            >
              <Share2 className="w-3.5 h-3.5" />
              Copy summary
            </button>
            <button
              disabled={!meeting.transcript}
              onClick={() => {
                const text = meeting.transcript || "";
                const blob = new Blob([text], { type: "text/plain" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `${title.replace(/[^\w\d]+/g, "_")}-transcript.txt`;
                a.click();
              }}
              style={{
                ...vbPrimaryBtnStyle,
                opacity: meeting.transcript ? 1 : 0.5,
                cursor: meeting.transcript ? "pointer" : "not-allowed",
              }}
            >
              <Download className="w-3.5 h-3.5" />
              Export
            </button>
          </div>
        </div>

        {/* Content */}
        <div
          className="flex-1 p-6 grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-4 min-h-0 overflow-hidden"
          style={{ background: "var(--vb-canvas)" }}
        >
          {/* Transcript */}
          <div
            className="overflow-hidden flex flex-col min-h-0"
            style={{
              background: "var(--vb-canvas)",
              border: "1px solid var(--vb-hairline)",
              borderRadius: 16,
            }}
          >
            <div
              className="px-5 py-3.5 flex items-center justify-between gap-3 shrink-0"
              style={{ borderBottom: "1px solid var(--vb-hairline-soft)" }}
            >
              <h3
                style={{
                  fontFamily: "var(--vb-font-display)",
                  fontWeight: 500,
                  fontSize: 16,
                  letterSpacing: "-0.3px",
                  color: "var(--vb-ink)",
                  margin: 0,
                }}
              >
                {meeting.status === "completed" ? "Transcript" : "Live transcript"}
              </h3>
              {/* <button
                onClick={() => setAiHighlightsOn(!aiHighlightsOn)}
                className={cn(
                  "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-medium transition-colors",
                  aiHighlightsOn
                    ? "bg-indigo-600 text-white hover:bg-indigo-700"
                    : "bg-slate-100 text-slate-500 hover:bg-slate-200",
                )}
                title="Toggle AI highlights"
              >
                <Sparkles className="w-3 h-3" />
                AI highlights
              </button> */}
            </div>
            <div
              ref={transcriptContainerRef}
              onScroll={handleTranscriptScroll}
              className="p-4 space-y-2 overflow-y-auto flex-1 [scrollbar-width:thin] [scrollbar-color:rgba(100,116,139,0.15)_transparent]"
            >
              {groups.length === 0 ? (
                <div className="text-center py-14">
                  <Inbox className="w-6 h-6 text-slate-300 mx-auto mb-2" />
                  <p className="text-xs font-medium text-slate-500">
                    No transcript yet
                  </p>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    Lines will stream in as the bot listens.
                  </p>
                </div>
              ) : (
                groups.map((group, idx) => (
                  <div
                    key={idx}
                    className={cn(
                      "flex gap-3 p-2.5 rounded-md",
                      group.isPartial
                        ? "bg-indigo-50/60"
                        : "hover:bg-slate-50/60",
                    )}
                  >
                    <div
                      className={cn(
                        "w-7 h-7 rounded-md flex items-center justify-center font-semibold text-[10px] text-white shrink-0",
                        colorFor(group.speaker),
                      )}
                    >
                      {getInitials(group.speaker)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline gap-2 mb-1">
                        <span className="text-[13px] font-semibold text-slate-900">
                          {group.speaker}
                        </span>
                        {group.timestamp && (
                          <span className="text-[10px] text-slate-400 tabular-nums">
                            {formatTime(group.timestamp)}
                          </span>
                        )}
                      </div>
                      <div className="space-y-1">
                        {group.messages.map((m, midx) => (
                          <p
                            key={midx}
                            className={cn(
                              "text-[13px] leading-relaxed",
                              group.isPartial
                                ? "text-slate-500 italic"
                                : "text-slate-700",
                            )}
                          >
                            {m}
                          </p>
                        ))}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Right column */}
          <div className="space-y-4 overflow-y-auto pr-1 min-h-0 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
            {/* Summary — cream surface card, matches mockup's AI summary treatment */}
            <div
              style={{
                background: "var(--vb-surface-card)",
                borderRadius: 20,
                padding: "20px 22px",
              }}
            >
              <div
                className="flex items-center gap-2"
                style={{ marginBottom: 14 }}
              >
                <Sparkles
                  className="w-3.5 h-3.5"
                  style={{ color: "var(--vb-lavender)" }}
                />
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    letterSpacing: "1px",
                    textTransform: "uppercase",
                    color: "var(--vb-muted)",
                  }}
                >
                  AI summary
                </span>
              </div>
              {meeting.summary ? (
                summaryBullets.length > 1 ? (
                  <ul className="space-y-2">
                    {summaryBullets.map((bullet, i) => (
                      <li key={i} className="flex items-start gap-2.5">
                        <span
                          style={{
                            width: 5,
                            height: 5,
                            borderRadius: "50%",
                            marginTop: 8,
                            flexShrink: 0,
                            background: "var(--vb-lavender)",
                          }}
                        />
                        <span
                          style={{
                            fontSize: 14,
                            lineHeight: 1.6,
                            color: "var(--vb-body-strong)",
                          }}
                        >
                          {bullet}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p
                    style={{
                      fontSize: 14,
                      lineHeight: 1.6,
                      color: "var(--vb-body-strong)",
                      margin: 0,
                    }}
                  >
                    {meeting.summary}
                  </p>
                )
              ) : (
                <p
                  className="italic"
                  style={{ fontSize: 12, color: "var(--vb-muted-soft)" }}
                >
                  No summary yet.
                </p>
              )}
            </div>

            {/* Agent insights (agents_v2 side-effect output) — ordered by
                the SKILL_ORDER map below so blockers/key-moments rank
                above softer signals. Unknown prompt_keys render as
                collapsible JSON. */}
            {sortInsights(agentInsights).map((ins) => (
              <AgentInsightCard key={ins.id} insight={ins} />
            ))}

            {/* Tasks */}
            <div
              className="overflow-hidden"
              style={{
                background: "var(--vb-canvas)",
                border: "1px solid var(--vb-hairline)",
                borderRadius: 16,
              }}
            >
              <div
                className="px-5 py-3.5 flex items-center justify-between gap-2"
                style={{ borderBottom: "1px solid var(--vb-hairline-soft)" }}
              >
                <h3
                  style={{
                    fontFamily: "var(--vb-font-display)",
                    fontWeight: 500,
                    fontSize: 16,
                    letterSpacing: "-0.3px",
                    color: "var(--vb-ink)",
                    margin: 0,
                  }}
                >
                  Tasks
                </h3>
                <div className="flex items-center gap-2">
                  {meeting?.id && <MeetingBoardLink meetingId={meeting.id} />}
                  <span
                    className="tabular-nums"
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: "var(--vb-muted)",
                      background: "var(--vb-surface-card)",
                      padding: "3px 9px",
                      borderRadius: 9999,
                    }}
                  >
                    {completedTaskCount}/{taskCount}
                  </span>
                </div>
              </div>
              {unassignedTaskCount > 0 && (
                <div className="mx-3 mt-3 px-3 py-2 bg-amber-50 border border-amber-100 rounded-md flex items-start gap-2">
                  <AlertCircle className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-0.5" />
                  <p className="text-xs font-medium text-amber-900 leading-snug">
                    {unassignedTaskCount}{" "}
                    {unassignedTaskCount === 1 ? "task needs" : "tasks need"} an
                    owner
                  </p>
                </div>
              )}
              <div className="p-2 space-y-1">
                {tasks.length === 0 ? (
                  <p className="px-4 py-6 text-xs text-slate-400 italic text-center">
                    No tasks extracted yet.
                  </p>
                ) : (
                  tasks.map((task) => {
                    const priorityKey = (task.priority || "medium").toLowerCase();
                    const priorityClass =
                      PRIORITY_STYLE[priorityKey] || PRIORITY_STYLE.medium;
                    const unassigned = isTaskUnassigned(task);
                    const due = formatDateShort(task.due_date);
                    const editingThis = editingTaskId === (task.id as number);
                    const savingThis = savingTaskId === (task.id as number);
                    const canEdit = typeof task.id === "number";
                    return (
                      <div
                        key={task.id}
                        className={cn(
                          "px-3 py-2.5 rounded-md border transition-colors",
                          unassigned
                            ? "border-l-2 border-l-amber-400 border-amber-100 bg-amber-50/30"
                            : "border-slate-100 hover:border-slate-200 hover:bg-slate-50/60",
                        )}
                      >
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <h4
                            className={cn(
                              "text-[13px] font-medium leading-snug",
                              task.is_completed
                                ? "text-slate-400 line-through"
                                : "text-slate-800",
                            )}
                          >
                            {task.task}
                          </h4>
                          <span
                            className={cn(
                              "px-1.5 py-0.5 text-[10px] font-medium rounded shrink-0 capitalize",
                              priorityClass,
                            )}
                          >
                            {priorityKey}
                          </span>
                        </div>
                        <div className="flex items-center justify-between gap-2 text-[11px]">
                          {unassigned && !due ? (
                            <button
                              onClick={() =>
                                canEdit && setEditingTaskId(task.id as number)
                              }
                              disabled={!canEdit}
                              className="group flex items-center gap-1 text-amber-700 italic hover:text-amber-900 disabled:cursor-default"
                              title={canEdit ? "Click to assign owner & date" : ""}
                            >
                              Unassigned owner & date
                              {canEdit && (
                                <Pencil className="w-2.5 h-2.5 opacity-40 group-hover:opacity-100" />
                              )}
                            </button>
                          ) : (
                            <>
                              <button
                                onClick={() =>
                                  canEdit && setEditingTaskId(task.id as number)
                                }
                                disabled={!canEdit}
                                className="group flex items-center gap-1.5 min-w-0 disabled:cursor-default"
                                title={
                                  canEdit ? "Click to change owner or date" : ""
                                }
                              >
                                <div
                                  className={cn(
                                    "w-5 h-5 text-white text-[9px] font-semibold rounded flex items-center justify-center shrink-0",
                                    colorFor(task.owner || "?"),
                                  )}
                                >
                                  {getInitials(task.owner || "?")}
                                </div>
                                <span
                                  className={cn(
                                    "truncate",
                                    unassigned
                                      ? "text-amber-700 italic"
                                      : "text-slate-600",
                                  )}
                                >
                                  {task.owner || "Unassigned owner"}
                                </span>
                                {canEdit && (
                                  <Pencil className="w-2.5 h-2.5 opacity-40 group-hover:opacity-100" />
                                )}
                              </button>
                              <button
                                onClick={() =>
                                  canEdit && setEditingTaskId(task.id as number)
                                }
                                disabled={!canEdit}
                                className={cn(
                                  "shrink-0 hover:text-indigo-600 disabled:cursor-default",
                                  due
                                    ? "text-slate-400"
                                    : "text-amber-700 italic",
                                )}
                                title={
                                  canEdit
                                    ? due
                                      ? "Click to change due date"
                                      : "Click to assign a due date"
                                    : ""
                                }
                              >
                                {due || "Unassigned date"}
                              </button>
                            </>
                          )}
                        </div>
                        {editingThis && canEdit && (
                          <div className="mt-2">
                            <TaskAssignmentEditor
                              open={editingThis}
                              initialOwner={task.owner ?? null}
                              initialDueDate={task.due_date ?? null}
                              participants={(meeting?.participants ?? []).map(
                                (p) => ({
                                  name: p.name,
                                  email: p.email,
                                  avatar_url: p.avatar_url,
                                }),
                              )}
                              onCancel={() => setEditingTaskId(null)}
                              onSave={(next) =>
                                saveTaskAssignment(task.id as number, next)
                              }
                              saving={savingThis}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            <MeetingAIMemorySection
              meetingId={meeting.id}
              meetingStatus={meeting.status}
              embeddingStatus={meeting.embedding_status}
              embeddedAt={meeting.embedded_at}
              graphStatus={meeting.graph_status}
              graphExtractedAt={meeting.graph_extracted_at}
              graphError={meeting.graph_error}
            />
          </div>
        </div>

        {/* LIVE INTELLIGENCE POPUP */}
        {activeNotification && (
          <div className="fixed bottom-6 right-6 z-[100] animate-in slide-in-from-right-10 duration-500">
            <div className="bg-slate-900 text-white p-4 rounded-xl shadow-lg border border-white/10 w-80 relative overflow-hidden">
              <div className="absolute -top-8 -right-8 w-24 h-24 bg-indigo-500/20 blur-2xl rounded-full" />
              <div className="flex items-start gap-3 relative z-10">
                <div className="shrink-0">
                  <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center shadow-lg">
                    <Zap className="w-4 h-4 text-white" />
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider">Task Detected</span>
                    <button onClick={() => setActiveNotification(null)} className="text-white/40 hover:text-white transition-colors"><CheckCircle2 className="w-3.5 h-3.5" /></button>
                  </div>
                  <h5 className="text-xs font-bold leading-snug text-white line-clamp-2">{activeNotification.payload.task}</h5>
                  <div className="mt-2 flex items-center gap-1.5 text-xs">
                    <div className={`w-4 h-4 rounded text-[7px] font-bold flex items-center justify-center ${colorFor(activeNotification.payload.owner || "?")}`}>{getInitials(activeNotification.payload.owner || "?")}</div>
                    <span className="text-white/70">Owner: <span className="text-white font-semibold">{activeNotification.payload.owner || "Unassigned owner"}</span></span>
                  </div>
                  {/* Due-date row — shows the ISO date if the LLM resolved one,
                      falls back to the raw phrase ("by Friday"), else amber italic
                      "Unassigned date" to mirror the persisted-task UI. */}
                  <div className="mt-1 flex items-center gap-1.5 text-xs">
                    <span className="text-white/70">Due: {(() => {
                      const iso = activeNotification.payload.due_date as string | undefined;
                      const phrase = activeNotification.payload.deadline as string | undefined;
                      const formatted = iso ? formatDateShort(iso) : null;
                      if (formatted) return <span className="text-white font-semibold">{formatted}</span>;
                      if (phrase) return <span className="text-white font-semibold">{phrase}</span>;
                      return <span className="text-amber-300 italic font-semibold">Unassigned date</span>;
                    })()}</span>
                  </div>
                </div>
              </div>
              <div className="absolute bottom-0 left-0 h-0.5 bg-indigo-500 animate-progress" style={{ width: '100%' }} />
            </div>
          </div>
        )}

        {/* Memory Phase 2 — in-meeting Q&A panel. Two render modes:
              closed → returns a floating right-edge tab (position:fixed)
              open   → returns the full panel, here mounted as a fixed
                       overlay on the right so we don't disturb the
                       existing grid layout. Cmd+K toggles. */}
        {askPanelOpen ? (
          <div className="fixed right-4 top-20 bottom-4 w-[420px] z-40 pointer-events-auto">
            <AskAssistantPanel
              meeting={{
                id: meeting.id,
                status: meeting.status,
                team: meeting.team,
                category: meeting.category,
              }}
              open
              onOpen={() => setAskPanelOpen(true)}
              onClose={() => setAskPanelOpen(false)}
            />
          </div>
        ) : (
          <AskAssistantPanel
            meeting={{
              id: meeting.id,
              status: meeting.status,
              team: meeting.team,
              category: meeting.category,
            }}
            open={false}
            onOpen={() => setAskPanelOpen(true)}
            onClose={() => setAskPanelOpen(false)}
          />
        )}
      </div>
    </Layout>
  );
}

// Higher = shown first. Missing keys sort to the bottom.
const SKILL_ORDER: Record<string, number> = {
  "blocker_detector": 100,
  "key_moments_extractor": 90,
  "commitment_watcher": 80,
  "insights.md": 70,             // legacy L&D four-bucket
  "followup_drafter": 60,
  "participant_sentiment": 50,
};

function sortInsights(items: AgentInsight[]): AgentInsight[] {
  return [...items].sort(
    (a, b) => (SKILL_ORDER[b.prompt_key] ?? 0) - (SKILL_ORDER[a.prompt_key] ?? 0),
  );
}

const SKILL_TITLE: Record<string, string> = {
  "blocker_detector": "Blockers",
  "key_moments_extractor": "Key Moments",
  "commitment_watcher": "Commitments",
  "insights.md": "L&D Insights",
  "followup_drafter": "Follow-up Draft",
  "participant_sentiment": "Participant Sentiment",
};

// ─── Vibrant primitives — button styles + status pill ──────────────────────

const vbPrimaryBtnStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 7,
  height: 40,
  padding: "0 15px",
  background: "var(--vb-ink)",
  color: "var(--vb-on-ink)",
  border: "none",
  borderRadius: 12,
  fontFamily: "var(--vb-font-sans)",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  textDecoration: "none",
};

const vbSecondaryBtnStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 7,
  height: 40,
  padding: "0 15px",
  background: "var(--vb-canvas)",
  border: "1px solid var(--vb-hairline)",
  borderRadius: 12,
  fontFamily: "var(--vb-font-sans)",
  fontSize: 13,
  fontWeight: 600,
  color: "var(--vb-body-strong)",
  cursor: "pointer",
  textDecoration: "none",
};

// Meeting status → vibrant color pair (matches MeetingCard's STATUS_STYLE).
const VB_STATUS: Record<string, { label: string; color: string; bg: string }> = {
  completed:  { label: "Completed",  color: "var(--vb-success)", bg: "color-mix(in srgb, var(--vb-success) 12%, white)" },
  processing: { label: "Processing", color: "var(--vb-info)",    bg: "color-mix(in srgb, var(--vb-info) 12%, white)" },
  pending:    { label: "Pending",    color: "var(--vb-warning)", bg: "color-mix(in srgb, var(--vb-warning) 14%, white)" },
  failed:     { label: "Failed",     color: "var(--vb-error)",   bg: "color-mix(in srgb, var(--vb-error) 12%, white)" },
};

function VbStatusPill({ status }: { status?: string | null }) {
  const s = VB_STATUS[status || ""] ?? VB_STATUS.pending;
  return (
    <span
      className="inline-flex items-center"
      style={{
        gap: 6,
        fontSize: 11,
        fontWeight: 600,
        padding: "4px 9px",
        borderRadius: 9999,
        color: s.color,
        background: s.bg,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: s.color,
        }}
      />
      {s.label}
    </span>
  );
}


function AgentInsightCard({ insight }: { insight: AgentInsight }) {
  const { prompt_key, payload } = insight;
  const title = SKILL_TITLE[prompt_key] || prompt_key;

  const body = renderInsightBody(prompt_key, payload);
  if (!body) return null;   // empty payloads suppress the card

  return (
    <div
      className="overflow-hidden"
      style={{
        background: "var(--vb-canvas)",
        border: "1px solid var(--vb-hairline)",
        borderRadius: 16,
      }}
    >
      <div
        className="px-5 py-3.5 flex items-center gap-2"
        style={{ borderBottom: "1px solid var(--vb-hairline-soft)" }}
      >
        <Sparkles className="w-3.5 h-3.5" style={{ color: "var(--vb-mint)" }} />
        <h3
          style={{
            fontFamily: "var(--vb-font-display)",
            fontWeight: 500,
            fontSize: 16,
            letterSpacing: "-0.3px",
            color: "var(--vb-ink)",
            margin: 0,
          }}
        >
          {title}
        </h3>
      </div>
      <div className="px-5 py-4">{body}</div>
    </div>
  );
}

// Returns null when payload has no items to show (so the card is hidden entirely).
function renderInsightBody(promptKey: string, payload: any): ReactNode {
  switch (promptKey) {
    case "insights.md":
      return renderLDInsights(payload);
    case "blocker_detector":
      return renderBlockers(payload);
    case "commitment_watcher":
      return renderCommitments(payload);
    case "key_moments_extractor":
      return renderKeyMoments(payload);
    case "participant_sentiment":
      return renderSentiment(payload);
    case "followup_drafter":
      return renderFollowup(payload);
    default:
      return renderUnknown(payload);
  }
}

function renderLDInsights(payload: any) {
  const gaps = payload?.training_gaps ?? [];
  const coaching = payload?.coaching_moments ?? [];
  const requests = payload?.skill_development_requests ?? [];
  const debrief = payload?.facilitator_debrief ?? [];
  if (!gaps.length && !coaching.length && !requests.length && !debrief.length) return null;
  return (
    <div className="space-y-4">
      {gaps.length > 0 && (
        <InsightList
          label="Training gaps"
          items={gaps.map((g: any) => ({
            primary: g.description,
            secondary: g.affected_person ? `Affected: ${g.affected_person}` : null,
          }))}
        />
      )}
      {coaching.length > 0 && (
        <InsightList
          label="Coaching moments"
          items={coaching.map((c: any) => ({
            primary: c.description,
            secondary: [
              c.delivered_by ? `From: ${c.delivered_by}` : null,
              c.received_by ? `To: ${c.received_by}` : null,
              c.tone,
            ].filter(Boolean).join(" · "),
          }))}
        />
      )}
      {requests.length > 0 && (
        <InsightList
          label="Skill development requests"
          items={requests.map((r: any) => ({
            primary: r.skill,
            secondary: r.learner ? `Learner: ${r.learner}` : null,
          }))}
        />
      )}
      {debrief.length > 0 && (
        <InsightList
          label="Facilitator debrief"
          items={debrief.map((d: any) => ({
            primary: d.observation,
            secondary: (d.category || "").replace(/_/g, " "),
          }))}
        />
      )}
    </div>
  );
}

function renderBlockers(payload: any) {
  const blockers = payload?.blockers ?? [];
  if (!blockers.length) return null;
  return (
    <ul className="space-y-3">
      {blockers.map((b: any, i: number) => (
        <li key={i} className="flex items-start gap-2.5">
          <span className="w-1 h-1 bg-red-600 rounded-full mt-2 shrink-0" />
          <div className="min-w-0">
            <p className="text-[13px] text-slate-700 leading-relaxed">
              {b.speaker && <span className="font-medium">{b.speaker}: </span>}
              {b.blocked_on}
              {b.waiting_on && (
                <span className="text-slate-500"> — waiting on {b.waiting_on}</span>
              )}
            </p>
            {b.evidence && (
              <p className="text-[11px] text-slate-500 mt-0.5 italic">
                "{b.evidence}"
              </p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

function renderCommitments(payload: any) {
  const delivered = payload?.delivered ?? [];
  const atRisk = payload?.at_risk ?? [];
  const fresh = payload?.new_commitment ?? [];
  if (!delivered.length && !atRisk.length && !fresh.length) return null;
  return (
    <div className="space-y-4">
      {delivered.length > 0 && (
        <InsightList
          label="Delivered"
          items={delivered.map((d: any) => ({
            primary: d.task,
            secondary: d.owner ? `by ${d.owner}` : null,
          }))}
        />
      )}
      {atRisk.length > 0 && (
        <InsightList
          label="At risk"
          items={atRisk.map((d: any) => ({
            primary: d.task,
            secondary: [d.owner, d.reason].filter(Boolean).join(" · "),
          }))}
        />
      )}
      {fresh.length > 0 && (
        <InsightList
          label="New commitment"
          items={fresh.map((d: any) => ({
            primary: d.commitment,
            secondary: [d.owner, d.related_task ? `re: ${d.related_task}` : null]
              .filter(Boolean).join(" · "),
          }))}
        />
      )}
    </div>
  );
}

function renderKeyMoments(payload: any) {
  const moments = payload?.moments ?? [];
  if (!moments.length) return null;
  const typeColor: Record<string, string> = {
    decision: "bg-indigo-100 text-indigo-800",
    reveal: "bg-emerald-100 text-emerald-800",
    reversal: "bg-amber-100 text-amber-800",
    disagreement: "bg-red-100 text-red-800",
  };
  return (
    <ul className="space-y-3">
      {moments.map((m: any, i: number) => (
        <li key={i} className="space-y-1">
          <div className="flex items-center gap-2">
            <span className={cn(
              "text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded",
              typeColor[m.type] || "bg-slate-200 text-slate-700",
            )}>{m.type}</span>
            {m.speaker && (
              <span className="text-[11px] text-slate-500 font-medium">{m.speaker}</span>
            )}
          </div>
          <blockquote className="text-[13px] text-slate-800 border-l-2 border-slate-200 pl-3 italic">
            "{m.quote}"
          </blockquote>
          {m.why_significant && (
            <p className="text-[11px] text-slate-500">{m.why_significant}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

function renderSentiment(payload: any) {
  const parts = payload?.participants ?? [];
  if (!parts.length) return null;
  const toneColor: Record<string, string> = {
    positive: "text-emerald-700",
    neutral: "text-slate-600",
    frustrated: "text-red-700",
    hesitant: "text-amber-700",
    assertive: "text-indigo-700",
  };
  return (
    <ul className="space-y-2">
      {parts.map((p: any, i: number) => (
        <li key={i} className="flex items-start gap-3">
          <span className="text-[13px] font-medium text-slate-800 min-w-24">
            {p.speaker}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[12px]">
              <span className={cn("font-medium", toneColor[p.tone] || "text-slate-700")}>
                {p.tone}
              </span>
              <span className="text-slate-400"> · engagement {p.engagement}</span>
            </p>
            {p.evidence && (
              <p className="text-[11px] text-slate-500 italic mt-0.5">"{p.evidence}"</p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

function renderFollowup(payload: any) {
  const subject = payload?.subject;
  const body = payload?.body_markdown;
  const recipients = payload?.recipients_hint;
  if (!subject && !body) return null;
  return (
    <div className="space-y-3">
      {subject && (
        <p className="text-[13px] font-semibold text-slate-900">{subject}</p>
      )}
      {recipients && (
        <p className="text-[11px] text-slate-500">
          Suggested recipients: {recipients}
        </p>
      )}
      {body && (
        <pre className="text-[12.5px] text-slate-700 whitespace-pre-wrap font-sans leading-relaxed bg-slate-50 rounded p-3 border border-slate-100">
          {body}
        </pre>
      )}
    </div>
  );
}

function renderUnknown(payload: any) {
  // Fallback: skill we don't have a bespoke renderer for. Show JSON so
  // outputs aren't lost while a real renderer is being built.
  return (
    <details className="text-[12px]">
      <summary className="text-slate-500 cursor-pointer">Raw output</summary>
      <pre className="mt-2 text-[11px] text-slate-700 bg-slate-50 rounded p-2 overflow-x-auto">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </details>
  );
}

function InsightList({
  label,
  items,
}: {
  label: string;
  items: { primary: string; secondary: string | null }[];
}) {
  return (
    <div>
      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
        {label}
      </h4>
      <ul className="space-y-2">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-2.5">
            <span className="w-1 h-1 bg-emerald-600 rounded-full mt-2 shrink-0" />
            <div className="min-w-0">
              <p className="text-[13px] text-slate-700 leading-relaxed">
                {it.primary}
              </p>
              {it.secondary && (
                <p className="text-[11px] text-slate-500 mt-0.5">
                  {it.secondary}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
