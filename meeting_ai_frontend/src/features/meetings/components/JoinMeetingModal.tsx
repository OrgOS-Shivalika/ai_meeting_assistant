import { useEffect, useMemo, useState } from "react";
import { X, Loader2, Video, Globe, Users } from "lucide-react";
import { useLocation } from "react-router-dom";
import { injectBot } from "../api";
import { useCategories } from "../hooks/useCategories";

interface JoinMeetingModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (meetingId: number) => void;
}

export default function JoinMeetingModal({ isOpen, onClose, onSuccess }: JoinMeetingModalProps) {
  const location = useLocation();
  const { data: categories } = useCategories();
  const [url, setUrl] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [teamId, setTeamId] = useState<number | null>(null);
  // Off by default, and deliberately not remembered between meetings — a
  // stale "in room" left on for a normal call would swap real participant
  // names for anonymous voice numbers. Opting in each time is cheap; opting
  // out after the fact is impossible, because the audio has already been
  // recorded one way or the other.
  const [inRoom, setInRoom] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Pre-fill from current URL filter when modal opens
  useEffect(() => {
    if (!isOpen) return;
    const params = new URLSearchParams(location.search);
    const presetCat = params.get("category_id");
    const presetTeam = params.get("team_id");
    setCategoryId(presetCat ? Number(presetCat) : null);
    setTeamId(presetTeam ? Number(presetTeam) : null);
    setUrl("");
    setInRoom(false);
    setError("");
  }, [isOpen, location.search]);

  const selectedCategory = useMemo(
    () => categories.find((c) => c.id === categoryId) ?? null,
    [categories, categoryId],
  );
  const availableTeams = selectedCategory?.teams ?? [];

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;

    setLoading(true);
    setError("");

    try {
      const response = await injectBot(url, {
        category_id: categoryId,
        team_id: teamId,
        capture_mode: inRoom ? "in_room" : "online",
      });
      onSuccess(response.meeting_id);
      onClose();
      setUrl("");
    } catch (err) {
      setError("Failed to start meeting bot. Please check the URL and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-md animate-in fade-in duration-300" onClick={onClose} />

      <div className="bg-canvas rounded-[2.5rem] shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in slide-in-from-bottom-8 duration-500 relative">
        <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/5 blur-3xl rounded-full -mr-16 -mt-16" />
        <div className="absolute bottom-0 left-0 w-32 h-32 bg-blue-500/5 blur-3xl rounded-full -ml-16 -mb-16" />

        <div className="px-8 pt-8 pb-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-3 bg-indigo-600 rounded-2xl shadow-soft shadow-indigo-600/20">
              <Video className="w-6 h-6 text-white" />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-slate-900">Join Meeting</h2>
              <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mt-0.5">Automated Intelligence</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-full transition-colors">
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-8">
          <div className="mb-5">
            <div className="flex items-center justify-between mb-2">
              <label htmlFor="meeting-url" className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Meeting URL
              </label>
              <div className="flex items-center gap-1 text-[10px] font-semibold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full">
                <Globe className="w-2.5 h-2.5" />
                Live
              </div>
            </div>
            <input
              id="meeting-url"
              type="url"
              required
              placeholder="meet.google.com/abc-defg-hij"
              className="w-full pl-4 pr-4 py-4 rounded-2xl border-2 border-slate-100 bg-slate-50/50 focus:bg-canvas focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-600 transition-all outline-hidden text-sm font-semibold text-slate-900 placeholder:text-slate-400"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>

          <div className="mb-5">
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-2">
              Category {categories.length === 0 && <span className="text-slate-300 font-normal normal-case ml-1">(optional — create one in the sidebar)</span>}
            </label>
            <select
              value={categoryId ?? ""}
              onChange={(e) => {
                const value = e.target.value ? Number(e.target.value) : null;
                setCategoryId(value);
                setTeamId(null);
              }}
              className="w-full px-4 py-3 rounded-2xl border-2 border-slate-100 bg-slate-50/50 focus:bg-canvas focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-600 transition-all outline-hidden text-sm font-semibold text-slate-900"
            >
              <option value="">No category</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {availableTeams.length > 0 && (
            <div className="mb-5">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-2">
                Team
              </label>
              <select
                value={teamId ?? ""}
                onChange={(e) =>
                  setTeamId(e.target.value ? Number(e.target.value) : null)
                }
                className="w-full px-4 py-3 rounded-2xl border-2 border-slate-100 bg-slate-50/50 focus:bg-canvas focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-600 transition-all outline-hidden text-sm font-semibold text-slate-900"
              >
                <option value="">No team</option>
                {availableTeams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <button
            type="button"
            onClick={() => setInRoom((v) => !v)}
            aria-pressed={inRoom}
            className={`w-full mb-5 p-4 rounded-2xl border-2 text-left transition-all active:scale-[0.99] ${
              inRoom
                ? "border-indigo-600 bg-indigo-50/60"
                : "border-slate-100 bg-slate-50/50 hover:bg-slate-50"
            }`}
          >
            <div className="flex items-start gap-3">
              <div
                className={`p-2 rounded-xl shrink-0 transition-colors ${
                  inRoom ? "bg-indigo-600" : "bg-slate-200"
                }`}
              >
                <Users
                  className={`w-4 h-4 ${inRoom ? "text-white" : "text-slate-500"}`}
                />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-slate-900">
                    Several people in one room
                  </span>
                  <span
                    className={`shrink-0 w-9 h-5 rounded-full transition-colors relative ${
                      inRoom ? "bg-indigo-600" : "bg-slate-300"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-all ${
                        inRoom ? "left-4.5" : "left-0.5"
                      }`}
                    />
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 leading-relaxed font-medium mt-1">
                  {inRoom
                    ? "Voices will be separated. Ask everyone to say their name once at the start so we can label them."
                    : "Turn this on if one laptop is sharing a room with 2 or more people."}
                </p>
              </div>
            </div>
          </button>

          <p className="mb-5 text-[11px] text-slate-500 leading-relaxed font-medium">
            We'll inject an AI assistant into your meeting to record, transcribe, and summarize automatically.
          </p>

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-100 text-red-600 text-xs font-semibold rounded-2xl flex items-center gap-3 animate-in shake duration-300">
              <div className="w-6 h-6 bg-red-100 rounded-lg flex items-center justify-center shrink-0">
                <span className="text-red-600">!</span>
              </div>
              {error}
            </div>
          )}

          <div className="flex flex-col sm:flex-row gap-3 mt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-6 py-4 border-2 border-slate-100 text-slate-600 font-semibold text-xs uppercase tracking-widest rounded-2xl hover:bg-slate-50 transition-all active:scale-[0.98]"
            >
              Back
            </button>
            <button
              type="submit"
              disabled={loading || !url}
              className="flex-1 px-6 py-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-200 disabled:text-slate-400 text-white font-semibold text-xs uppercase tracking-widest rounded-2xl shadow-raised shadow-indigo-600/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 group"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Connecting
                </>
              ) : (
                <>
                  Start Session
                  <span className="group-hover:translate-x-1 transition-transform">→</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
