import { Link, useParams } from "react-router-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchMeetingById } from "../api";
import Layout from "../../../shared/components/Layout";
import CategoryAssignControl from "../components/CategoryAssignControl";
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
  Radio,
  Zap,
} from "lucide-react";
import type { Meeting, Participant, Task } from "../types";
import MeetingAIMemorySection from "../components/MeetingAIMemorySection";
import {
  useLiveTranscript,
  type LiveFinal,
} from "../hooks/useLiveTranscript";

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
  high: "bg-rose-50 text-rose-700 ring-rose-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  low: "bg-slate-50 text-slate-600 ring-slate-200",
};

const STATUS_STYLE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  failed: "bg-rose-50 text-rose-700 ring-rose-200",
  pending: "bg-amber-50 text-amber-700 ring-amber-200",
  processing: "bg-indigo-50 text-indigo-700 ring-indigo-200",
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
  const [error, setError] = useState<string | null>(null);
  const [aiHighlightsOn, setAiHighlightsOn] = useState(false);
  
  const [activeNotification, setActiveNotification] = useState<any | null>(null);
  const [liveTasks, setLiveTasks] = useState<Task[]>([]);
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
             due_date: payload.deadline || null,
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
    return [...base, ...fresh];
  }, [meeting, liveTasks]);

  if (error) {
    return (
      <Layout>
        <div className="max-w-3xl mx-auto px-4 py-12">
          <div className="bg-white rounded-xl border border-slate-200 p-8 text-center">
            <AlertCircle className="w-10 h-10 text-rose-500 mx-auto mb-3" />
            <h2 className="text-lg font-bold text-slate-900 mb-1">
              Couldn't load meeting
            </h2>
            <p className="text-sm text-slate-500 mb-5">{error}</p>
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-bold transition-all"
            >
              <ChevronLeft className="w-4 h-4" />
              Back to meetings
            </Link>
          </div>
        </div>
      </Layout>
    );
  }

  if (!meeting) {
    return (
      <Layout>
        <div className="flex justify-center items-center h-[60vh]">
          <div className="relative w-10 h-10">
            <div className="absolute inset-0 rounded-full border-3 border-gray-200" />
            <div className="absolute inset-0 rounded-full border-t-3 border-[#4F46E5] animate-spin" />
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
  const statusBadge = STATUS_STYLE[meeting.status] || "bg-slate-50 text-slate-700 ring-slate-200";

  return (
    <Layout>
      <div className="max-w-[1400px] mx-auto h-[calc(100vh-64px)] pb-6 flex flex-col">
        <div className="bg-white rounded-[24px] border border-gray-200 shadow-2xl shadow-slate-200/40 overflow-hidden flex flex-col flex-1">
          {/* Top Navigation Bar */}
          <div className="px-8 py-3.5 flex items-center justify-between border-b border-gray-100 bg-white shrink-0">
            <div className="flex items-center gap-2 text-[10px] font-medium text-slate-400 min-w-0">
              <Link to="/" className="hover:text-indigo-600 transition-colors">Meetings</Link>
              {meeting.category && (
                <>
                  <span className="text-slate-300">/</span>
                  <Link to={`/?category_id=${meeting.category.id}`} className="hover:text-indigo-600 transition-colors" style={{ color: meeting.category.color || undefined }}>
                    {meeting.category.name}
                  </Link>
                </>
              )}
              <span className="text-slate-300">/</span>
              <span className="text-slate-500 font-semibold truncate">{title}</span>
            </div>
            <div className="flex items-center gap-4 shrink-0">
              <CategoryAssignControl
                meetingId={meeting.id}
                category={meeting.category}
                team={meeting.team}
                onChange={({ category, team }) => setMeeting((prev) => prev ? { ...prev, category, team } : prev)}
              />
            </div>
          </div>

          {/* Header Section */}
          <div className="px-8 pt-8 pb-7 flex flex-col lg:flex-row lg:items-end justify-between gap-6 border-b border-gray-50 shrink-0">
            <div className="space-y-3.5 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ring-1 ${statusBadge}`}>
                  {meeting.status}
                </span>
                {meeting.meeting_platform && (
                  <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-slate-50 text-slate-600 ring-1 ring-slate-200">
                    {meeting.meeting_platform.replace(/_/g, " ")}
                  </span>
                )}
              </div>
              <h1 className="text-[26px] font-bold text-[#0F1523] tracking-tight leading-tight">{title}</h1>
              <div className="flex items-center gap-5 text-[11px] font-medium text-slate-400 flex-wrap">
                <div className="flex items-center gap-1.5"><Calendar className="w-3.5 h-3.5" /><span>{dateStr}</span></div>
                {durationStr && <div className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5" /><span>{durationStr}</span></div>}
                <div className="flex items-center gap-1.5"><Users className="w-3.5 h-3.5" /><span>{participants.length} participants</span></div>
              </div>
            </div>

            <div className="flex items-center gap-2.5 flex-wrap">
              {meeting.meeting_url && (
                <a href={meeting.meeting_url} target="_blank" rel="noreferrer" className="h-8.5 px-4 bg-white border border-gray-200 text-[#0F1523] font-bold text-[10px] uppercase rounded-lg hover:bg-slate-50 transition-all flex items-center gap-2">
                  <ExternalLink className="w-3.5 h-3.5" /> Open Meeting
                </a>
              )}
              <button disabled={!meeting.summary} onClick={() => meeting.summary && navigator.clipboard?.writeText(meeting.summary)} className="h-8.5 px-4 bg-white border border-gray-200 text-[#0F1523] font-bold text-[10px] uppercase rounded-lg hover:bg-slate-50 flex items-center gap-2 disabled:opacity-40"><Share2 className="w-3.5 h-3.5" /> Copy Summary</button>
              <button disabled={!meeting.transcript} onClick={() => {
                  const text = meeting.transcript || "";
                  const blob = new Blob([text], { type: "text/plain" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `${title.replace(/[^\w\d]+/g, "_")}-transcript.txt`;
                  a.click();
                }} className="h-8.5 px-4 bg-white border border-gray-200 text-[#0F1523] font-bold text-[10px] uppercase rounded-lg hover:bg-slate-50 flex items-center gap-2 disabled:opacity-40"><Download className="w-3.5 h-3.5" /> Export</button>
            </div>
          </div>

          {/* Content Layout */}
          <div className="flex-1 bg-[#F9FAFC] p-8 grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-6 min-h-0 overflow-hidden">
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col min-h-0">
              <div className="px-6 py-3.5 bg-[#F8F9FB] border-b border-gray-100 flex items-center justify-between gap-3 shrink-0">
                <div className="flex items-center gap-2.5">
                  <span className="text-[11px] font-bold text-slate-600 uppercase tracking-widest">
                    {meeting.status === "completed" ? "Full Transcript" : "Live Transcript"}
                  </span>
                  {connected && <span className="inline-flex items-center gap-1 text-[9px] font-black uppercase tracking-widest px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700"><Radio className="w-2.5 h-2.5" />Live</span>}
                </div>
                <button onClick={() => setAiHighlightsOn(!aiHighlightsOn)} className={`px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-all ${aiHighlightsOn ? "bg-[#4F46E5] text-white" : "bg-slate-200 text-slate-50"}`}>
                  <Sparkles className="w-3 h-3" /><span className="text-[9px] font-black uppercase">AI Highlights</span>
                </button>
              </div>

              <div ref={transcriptContainerRef} onScroll={handleTranscriptScroll} className="p-7 space-y-7 overflow-y-auto flex-1 scrollbar-thin scrollbar-thumb-slate-200 scrollbar-track-transparent">
                {groups.length === 0 ? (
                  <div className="text-center py-12"><Inbox className="w-8 h-8 text-slate-300 mx-auto mb-3" /><p className="text-sm font-bold text-slate-500">No transcript yet</p></div>
                ) : (
                  groups.map((group, idx) => (
                    <div key={idx} className="relative">
                      <div className={`flex gap-5 p-3.5 rounded-xl ${group.isPartial ? "bg-indigo-50/40 ring-1 ring-indigo-100" : ""}`}>
                        <div className="shrink-0 mt-0.5">
                          <div className={`w-8.5 h-8.5 rounded-md flex items-center justify-center font-bold text-[11px] text-white shadow-xs ${colorFor(group.speaker)}`}>
                            {getInitials(group.speaker)}
                          </div>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2.5 mb-2">
                            <span className="text-[12.5px] font-bold text-[#0F1523]">{group.speaker}</span>
                            {group.timestamp && <span className="text-[9.5px] font-semibold text-slate-400 uppercase tracking-tighter">{formatTime(group.timestamp)}</span>}
                          </div>
                          <div className="space-y-2">
                            {group.messages.map((m, midx) => (
                              <p key={midx} className={`text-[12.5px] leading-relaxed font-medium ${group.isPartial ? "text-slate-500 italic" : "text-slate-600"}`}>
                                {m}
                              </p>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="space-y-6 overflow-y-auto pr-2 scrollbar-thin">
              {/* Meeting Summary Card */}
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-7 border-b-[3px] border-b-gray-100">
                <div className="flex items-center gap-2.5 mb-5">
                  <Sparkles className="w-4 h-4 text-[#4F46E5]" />
                  <h3 className="text-[11px] font-black text-slate-900 uppercase tracking-[0.15em]">Meeting Summary</h3>
                </div>
                {meeting.summary ? (
                  summaryBullets.length > 1 ? (
                    <div className="space-y-3.5">
                      {summaryBullets.map((bullet, i) => (
                        <div key={i} className="flex items-start gap-3">
                          <div className="w-1.5 h-1.5 bg-[#4F46E5] rounded-full mt-1.5 shadow-[0_0_6px_rgba(79,70,229,0.3)]" />
                          <span className="text-[11.5px] text-slate-700 font-bold leading-relaxed">{bullet}</span>
                        </div>
                      ))}
                    </div>
                  ) : <p className="text-[11.5px] text-slate-700 font-bold leading-relaxed">{meeting.summary}</p>
                ) : <p className="text-[11.5px] text-slate-400 italic">No summary yet.</p>}
              </div>

              {/* Assigned Tasks Card */}
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden border-b-[3px] border-b-gray-100">
                <div className="px-7 py-4.5 border-b border-gray-50 bg-slate-50/30 flex items-center justify-between">
                  <h3 className="text-[11px] font-black text-slate-900 uppercase tracking-[0.15em]">Assigned Tasks</h3>
                  <span className="text-[10px] font-black text-slate-400">{completedTaskCount} / {taskCount}</span>
                </div>
                {unassignedTaskCount > 0 && (
                  <div className="mx-3 mt-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-2">
                    <AlertCircle className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-0.5" />
                    <p className="text-[10.5px] font-bold text-amber-900 leading-snug">{unassignedTaskCount} tasks need an owner.</p>
                  </div>
                )}
                <div className="p-3 space-y-1.5">
                  {tasks.length === 0 ? <p className="px-4 py-6 text-[11.5px] text-slate-400 italic text-center">No tasks captured.</p> : tasks.map((task) => {
                      const priorityKey = (task.priority || "medium").toLowerCase();
                      const priorityClass = PRIORITY_STYLE[priorityKey] || PRIORITY_STYLE.medium;
                      const unassigned = isTaskUnassigned(task);
                      const due = formatDateShort(task.due_date);
                      return (
                        <div key={task.id} className={`px-4 py-3.5 rounded-xl border ${unassigned ? "border-l-[3px] border-l-amber-400 border-amber-100 bg-amber-50/30" : "border-transparent hover:border-slate-100 hover:bg-slate-50"} transition-all flex flex-col gap-2.5`}>
                          <div className="flex items-start justify-between gap-3">
                            <h4 className={`text-[11.5px] font-bold leading-snug ${task.is_completed ? "text-slate-400 line-through" : "text-slate-800"}`}>{task.task}</h4>
                            <span className={`px-2 py-0.5 text-[8px] font-black uppercase rounded-md ring-1 tracking-wider ${priorityClass}`}>{priorityKey}</span>
                          </div>
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 min-w-0">
                              <div className={`w-5 h-5 text-white text-[8px] font-black rounded-md flex items-center justify-center shadow-xs ${colorFor(task.owner || "?")}`}>{getInitials(task.owner || "?")}</div>
                              <span className={`text-[10px] font-bold truncate ${unassigned ? "text-amber-700 italic" : "text-slate-500"}`}>{task.owner || "Unassigned"}</span>
                            </div>
                            {due && <span className="text-[9.5px] font-black text-slate-400 uppercase tracking-tighter">Due {due}</span>}
                          </div>
                        </div>
                      );
                    })}
                </div>
              </div>

              <MeetingAIMemorySection
                meetingId={meeting.id}
                embeddingStatus={meeting.embedding_status}
                embeddedAt={meeting.embedded_at}
                graphStatus={meeting.graph_status}
                graphExtractedAt={meeting.graph_extracted_at}
                graphError={meeting.graph_error}
              />
            </div>
          </div>
        </div>

        {/* LIVE INTELLIGENCE POPUP */}
        {activeNotification && (
          <div className="fixed bottom-8 right-8 z-[100] animate-in slide-in-from-right-10 duration-500">
            <div className="bg-[#0F1523] text-white p-5 rounded-[20px] shadow-2xl border border-white/10 w-[320px] relative overflow-hidden group">
              <div className="absolute -top-10 -right-10 w-32 h-32 bg-indigo-500/20 blur-[40px] rounded-full" />
              <div className="flex items-start gap-4 relative z-10">
                <div className="shrink-0">
                  <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                    <Zap className="w-5 h-5 text-white" />
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-black text-indigo-400 uppercase tracking-widest">Live Task Detected</span>
                    <button onClick={() => setActiveNotification(null)} className="text-white/40 hover:text-white transition-colors"><CheckCircle2 className="w-4 h-4" /></button>
                  </div>
                  <h5 className="text-[13px] font-bold leading-snug text-white line-clamp-2">{activeNotification.payload.task}</h5>
                  <div className="mt-3 flex items-center gap-2">
                    <div className={`w-5 h-5 rounded-md flex items-center justify-center text-[9px] font-black shadow-xs ${colorFor(activeNotification.payload.owner || "?")}`}>{getInitials(activeNotification.payload.owner || "?")}</div>
                    <span className="text-[10px] font-bold text-white/60">Owner: <span className="text-white">{activeNotification.payload.owner || "Unassigned"}</span></span>
                  </div>
                </div>
              </div>
              <div className="absolute bottom-0 left-0 h-1 bg-indigo-500 animate-progress" style={{ width: '100%' }} />
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
