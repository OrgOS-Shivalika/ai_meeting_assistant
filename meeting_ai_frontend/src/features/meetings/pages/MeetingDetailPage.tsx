import { useParams } from "react-router-dom";
import { useEffect, useState, useRef, useMemo } from "react";
import { fetchMeetingById } from "../api";
import Layout from "../../../shared/components/Layout";
import CategoryAssignControl from "../components/CategoryAssignControl";
import {
  Calendar,
  Clock,
  Users,
  Bell,
  Sparkles,
  Share2,
  Download,
  Play,
  ChevronRight,
} from "lucide-react";

type LiveLine = { speaker: string; text: string; timestamp: number };
type TranscriptGroup = {
  speaker: string;
  timestamp?: number | string;
  messages: string[];
  isHighlighted?: boolean;
};

const getInitials = (name: string) => {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
};

const formatTime = (ts?: number | string) => {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "10:04 AM";
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
};

export default function MeetingDetailPage() {
  const { id } = useParams();
  const [meeting, setMeeting] = useState<any>(null);
  const [aiHighlightsOn, setAiHighlightsOn] = useState(true);
  const [liveLines, setLiveLines] = useState<LiveLine[]>([]);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchMeetingById(id!).then((data) => {
      setMeeting(data);
      if (data.transcript) {
        const parseLine = (line: string) => {
          const colonIdx = line.indexOf(": ");
          if (colonIdx < 0) return { speaker: "Unknown", text: line };
          return {
            speaker: line.slice(0, colonIdx),
            text: line.slice(colonIdx + 2),
          };
        };
        const lines: LiveLine[] = data.transcript
          .split("\n")
          .filter((l: string) => l.trim())
          .map((line: string) => ({
            ...parseLine(line),
            timestamp: Date.now(),
          }));
        setLiveLines(lines);
      }
    });
  }, [id]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [liveLines]);

  const groups = useMemo<TranscriptGroup[]>(() => {
    if (meeting?.status === "completed" && meeting?.transcript_raw) {
      const raw = meeting.transcript_raw;
      const gs: TranscriptGroup[] = [];
      for (let i = 0; i < raw.length; i++) {
        const item = raw[i];
        const speaker = item.participant?.name || "Unknown";
        const text = (item.words || []).map((w: any) => w.text).join(" ");
        const ts = item.words?.[0]?.start_timestamp?.absolute;
        const last = gs[gs.length - 1];

        const isHighlighted =
          aiHighlightsOn && (speaker.includes("Mike T") || i === 1);

        if (last && last.speaker === speaker) {
          last.messages.push(text);
          if (isHighlighted) last.isHighlighted = true;
        } else {
          gs.push({ speaker, timestamp: ts, messages: [text], isHighlighted });
        }
      }
      return gs;
    }

    const lines =
      liveLines.length > 0
        ? liveLines
        : [
            {
              speaker: "Sarah J.",
              text: "Welcome everyone to our Q3 strategy sync. We have a lot to cover today regarding the roadmap.",
              timestamp: Date.now() - 100000,
            },
            {
              speaker: "Mike T.",
              text: "I've reviewed the current capacity and I think we should prioritize the mobile-first indexing for this quarter. It's our biggest bottleneck.",
              timestamp: Date.now() - 80000,
            },
            {
              speaker: "Kevin L.",
              text: "Agreed. The Prism design system update is also critical for the consistency across our mobile apps.",
              timestamp: Date.now() - 60000,
            },
          ];

    const gs: TranscriptGroup[] = [];
    lines.forEach((line) => {
      const last = gs[gs.length - 1];
      const isHighlighted = aiHighlightsOn && line.speaker.includes("Mike T");
      if (last && last.speaker === line.speaker) {
        last.messages.push(line.text);
        if (isHighlighted) last.isHighlighted = true;
      } else {
        gs.push({
          speaker: line.speaker,
          timestamp: line.timestamp,
          messages: [line.text],
          isHighlighted,
        });
      }
    });
    return gs;
  }, [meeting, liveLines, aiHighlightsOn]);

  if (!meeting) return null;

  const dateStr = "Oct 24, 2023"; // Exact per reference

  return (
    <Layout>
      <div className="max-w-[1400px] mx-auto">
        {/* Outer Rounded Container */}
        <div className="bg-white rounded-[24px] border border-gray-200 shadow-2xl shadow-slate-200/40 overflow-hidden flex flex-col min-h-[calc(100vh-80px)]">
          {/* Top Navigation Bar */}
          <div className="px-8 py-3.5 flex items-center justify-between border-b border-gray-100 bg-white">
            <div className="flex items-center gap-2 text-[10px] font-medium text-slate-400">
              <span>Meetings</span>
              <span className="text-slate-300">/</span>
              <span className="text-slate-500 font-semibold">
                {meeting.title || "Q3 Product Strategy Sync"}
              </span>
            </div>
            <div className="flex items-center gap-4">
              <CategoryAssignControl
                meetingId={meeting.id}
                category={meeting.category}
                team={meeting.team}
                onChange={({ category, team }) =>
                  setMeeting((prev: any) =>
                    prev ? { ...prev, category, team } : prev,
                  )
                }
              />
              <Bell className="w-3.5 h-3.5 text-slate-400 cursor-pointer hover:text-indigo-600 transition-colors" />
              <div className="w-6 h-6 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center cursor-pointer hover:border-indigo-300 transition-colors">
                <div className="w-3 h-3 bg-slate-300 rounded-full" />
              </div>
            </div>
          </div>

          {/* Header Section */}
          <div className="px-8 pt-8 pb-7 flex flex-col lg:flex-row lg:items-end justify-between gap-6 border-b border-gray-50">
            <div className="space-y-3.5">
              <h1 className="text-[26px] font-bold text-[#0F1523] tracking-tight leading-none">
                Meeting Review: {meeting.title || "Q3 Product Strategy Sync"}
              </h1>
              <div className="flex items-center gap-5 text-[11px] font-medium text-slate-400">
                <div className="flex items-center gap-1.5">
                  <Calendar className="w-3.5 h-3.5 text-slate-300" />
                  <span>{dateStr}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-slate-300" />
                  <span>45 min</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Users className="w-3.5 h-3.5 text-slate-300" />
                  <span>8 Participants</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <button className="h-8.5 px-4 bg-white border border-gray-200 text-[#0F1523] font-bold text-[10px] uppercase tracking-wider rounded-lg hover:bg-slate-50 transition-all shadow-xs flex items-center gap-2">
                <Share2 className="w-3.5 h-3.5" /> Share Summary
              </button>
              <button className="h-8.5 px-4 bg-white border border-gray-200 text-[#0F1523] font-bold text-[10px] uppercase tracking-wider rounded-lg hover:bg-slate-50 transition-all shadow-xs flex items-center gap-2">
                <Download className="w-3.5 h-3.5" /> Export Transcript
              </button>
              <button className="h-8.5 px-5 bg-[#4F46E5] text-white font-bold text-[10px] uppercase tracking-wider rounded-lg hover:bg-[#4338CA] transition-all shadow-sm shadow-indigo-200 flex items-center gap-2">
                Edit Tasks
              </button>
            </div>
          </div>

          {/* Content Layout */}
          <div className="flex-1 bg-[#F9FAFC] p-8 grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-6">
            {/* LEFT COLUMN: Transcript Panel */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col border-b-[3px] border-b-gray-100">
              <div className="px-6 py-3.5 bg-[#F8F9FB] border-b border-gray-100 flex items-center justify-between">
                <span className="text-[11px] font-bold text-slate-600 uppercase tracking-widest">
                  Full Transcript
                </span>
                <button
                  onClick={() => setAiHighlightsOn(!aiHighlightsOn)}
                  className={`px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-all ${
                    aiHighlightsOn
                      ? "bg-[#4F46E5] text-white shadow-md shadow-indigo-100"
                      : "bg-slate-200 text-slate-500"
                  }`}
                >
                  <Sparkles
                    className={`w-3 h-3 ${aiHighlightsOn ? "fill-white" : ""}`}
                  />
                  <span className="text-[9px] font-black uppercase tracking-wider">
                    AI Highlights {aiHighlightsOn ? "On" : "Off"}
                  </span>
                </button>
              </div>

              <div className="p-7 space-y-7 overflow-y-auto max-h-[700px] scrollbar-thin scrollbar-thumb-slate-200 scrollbar-track-transparent">
                {groups.map((group, idx) => (
                  <div key={idx} className="relative">
                    {/* AI Generated Context Box */}
                    {idx === 2 && aiHighlightsOn && (
                      <div className="mb-8 p-5 bg-[#F5F3FF] border border-dashed border-[#C7D2FE] rounded-xl animate-in fade-in slide-in-from-top-2 duration-500">
                        <div className="flex items-center gap-2 mb-2.5">
                          <Sparkles className="w-3.5 h-3.5 text-[#4F46E5] fill-[#4F46E5]/10" />
                          <span className="text-[10px] font-black text-[#4F46E5] uppercase tracking-widest">
                            AI-Generated Context
                          </span>
                        </div>
                        <p className="text-[11.5px] text-slate-600 leading-relaxed font-medium mb-3">
                          Kevin is referring to the 'Prism' design system update
                          discussed in the previous meeting on July 14th.
                        </p>
                        <button className="text-[10px] font-bold text-[#4F46E5] hover:underline flex items-center gap-1 group">
                          View related meeting{" "}
                          <ChevronRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
                        </button>
                      </div>
                    )}

                    <div
                      className={`flex gap-5 p-3.5 rounded-xl transition-all ${group.isHighlighted ? "bg-[#F8F9FC] border-l-[3px] border-[#4F46E5] shadow-xs" : ""}`}
                    >
                      <div className="shrink-0 mt-0.5">
                        <div className="w-8.5 h-8.5 bg-[#EEF2FF] text-[#4F46E5] rounded-[6px] flex items-center justify-center font-bold text-[11px] border border-[#E0E7FF] shadow-xs">
                          {getInitials(group.speaker)}
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2.5">
                            <span className="text-[12.5px] font-bold text-[#0F1523]">
                              {group.speaker}
                            </span>
                            <span className="text-[9.5px] font-semibold text-slate-400 uppercase tracking-tighter">
                              {formatTime(group.timestamp)}
                            </span>
                          </div>
                          {group.isHighlighted && (
                            <span className="text-[8.5px] font-black text-[#4F46E5] uppercase tracking-[0.12em] bg-indigo-50 px-1.5 py-0.5 rounded">
                              Key Decision
                            </span>
                          )}
                        </div>
                        <div className="space-y-2">
                          {group.messages.map((m, midx) => (
                            <p
                              key={midx}
                              className="text-[12.5px] text-slate-600 leading-relaxed font-medium"
                            >
                              {m}
                            </p>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
                <div ref={transcriptEndRef} />
              </div>
            </div>

            {/* RIGHT COLUMN: Sidebar Cards */}
            <div className="space-y-6">
              {/* 1. Meeting Summary Card */}
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-7 border-b-[3px] border-b-gray-100">
                <div className="flex items-center gap-2.5 mb-5">
                  <Sparkles className="w-4 h-4 text-[#4F46E5]" />
                  <h3 className="text-[11px] font-black text-slate-900 uppercase tracking-[0.15em]">
                    Meeting Summary
                  </h3>
                </div>
                <p className="text-[11.5px] text-slate-500 leading-relaxed font-medium mb-6">
                  The team discussed the Q3 product strategy, focusing on
                  mobile-first indexing and the upcoming backend refactor.
                </p>
                <div className="space-y-3.5">
                  {[
                    "Mobile-first indexing prioritized",
                    "Backend refactor at 80%",
                    "Design system pushed to staging",
                  ].map((bullet, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <div className="w-1.5 h-1.5 bg-[#4F46E5] rounded-full shrink-0 shadow-[0_0_6px_rgba(79,70,229,0.3)]" />
                      <span className="text-[11.5px] text-slate-700 font-bold">
                        {bullet}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* 2. Assigned Tasks Card */}
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden border-b-[3px] border-b-gray-100">
                <div className="px-7 py-4.5 border-b border-gray-50 flex items-center justify-between bg-slate-50/30">
                  <h3 className="text-[11px] font-black text-slate-900 uppercase tracking-[0.15em]">
                    Assigned Tasks
                  </h3>
                  <span className="text-[10px] font-black text-slate-400 uppercase">
                    3 Items
                  </span>
                </div>
                <div className="p-3 space-y-1.5">
                  {[
                    {
                      title: "Finalize API latency report",
                      urgent: true,
                      owner: "SJ",
                      due: "Jul 28",
                    },
                    {
                      title: "Component token audit",
                      owner: "MT",
                      due: "Jul 30",
                    },
                    {
                      title: "Update Beta stakeholder deck",
                      owner: "KL",
                      due: "Aug 02",
                    },
                  ].map((task, i) => (
                    <div
                      key={i}
                      className="px-4 py-3.5 rounded-xl hover:bg-slate-50 transition-all flex flex-col gap-2.5 cursor-pointer border border-transparent hover:border-slate-100"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <h4 className="text-[11.5px] font-bold text-slate-800 leading-snug line-clamp-2">
                          {task.title}
                        </h4>
                        {task.urgent && (
                          <span className="shrink-0 px-2 py-0.5 bg-red-50 text-red-600 text-[7px] font-black uppercase rounded-md border border-red-100 tracking-wider">
                            URGENT
                          </span>
                        )}
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-5 h-5 bg-[#4F46E5] text-white text-[8px] font-black rounded-md flex items-center justify-center border border-indigo-200 shadow-xs">
                            {task.owner}
                          </div>
                          <span className="text-[10px] font-bold text-slate-400">
                            Sarah J.
                          </span>
                        </div>
                        <span className="text-[9.5px] font-black text-slate-300 uppercase tracking-tighter">
                          Due {task.due}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 3. Metadata Card */}
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-7 space-y-6 border-b-[3px] border-b-gray-100">
                <div className="space-y-4">
                  <div className="flex items-center justify-between py-1">
                    <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">
                      Date
                    </span>
                    <span className="text-[11.5px] font-bold text-slate-800">
                      {dateStr}
                    </span>
                  </div>
                  <div className="h-px bg-slate-50" />
                  <div className="flex items-center justify-between py-1">
                    <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">
                      Duration
                    </span>
                    <span className="text-[11.5px] font-bold text-slate-800">
                      45 Minutes
                    </span>
                  </div>
                  <div className="h-px bg-slate-50" />
                  <div className="space-y-3.5">
                    <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest block mb-1">
                      Participants
                    </span>
                    <div className="flex items-center justify-between">
                      <div className="flex -space-x-2">
                        {["SJ", "MT", "KL", "AR"].map((init, i) => (
                          <div
                            key={i}
                            className={`w-7 h-7 rounded-full border-2 border-white flex items-center justify-center text-[9px] font-black shadow-xs ring-1 ring-slate-100 ${i === 3 ? "bg-slate-50 text-slate-400" : "bg-indigo-50 text-indigo-600"}`}
                          >
                            {i === 3 ? "+6" : init}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                <button className="w-full h-9 flex items-center justify-center gap-2 border border-gray-200 text-slate-600 font-black text-[10px] uppercase tracking-[0.15em] rounded-lg hover:bg-slate-50 hover:border-slate-300 transition-all active:scale-[0.98]">
                  <Play className="w-3.5 h-3.5 fill-slate-300 text-slate-300" />{" "}
                  Watch Recording
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Page Footer / Legal */}
        <div className="mt-8 pb-8 text-[9px] font-bold text-slate-300 uppercase tracking-[0.2em] flex items-center justify-center gap-4">
          <span>© 2024 MeetingOps Intelligence</span>
          <div className="w-1 h-1 bg-slate-200 rounded-full" />
          <span>Enterprise Organizational Memory</span>
        </div>
      </div>
    </Layout>
  );
}
