import { useEffect, useMemo, useState } from "react";
import {
  Calendar,
  CalendarCheck,
  CalendarPlus,
  ChevronDown,
  Clock,
  Loader2,
  Mail,
  Tag,
  Users,
  Link as LinkIcon,
} from "lucide-react";
import { scheduleTeamMeeting } from "../api";
import { useCategories } from "../hooks/useCategories";
import type { Meeting } from "../types";

interface ScheduleMeetingFormProps {
  defaultCategoryId?: number | null;
  defaultTeamId?: number | null;
  onScheduled: (meeting: Meeting) => void;
}

const PLATFORMS = [
  { value: "", label: "Auto-detect" },
  { value: "google_meet", label: "Google Meet" },
  { value: "zoom", label: "Zoom" },
  { value: "teams", label: "Microsoft Teams" },
  { value: "webex", label: "Webex" },
];

// Local-time ISO string (YYYY-MM-DDTHH:mm) used as the min for the
// datetime-local input so users can't pick a past slot.
const nowLocalISO = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
};

export default function ScheduleMeetingForm({
  defaultCategoryId = null,
  defaultTeamId = null,
  onScheduled,
}: ScheduleMeetingFormProps) {
  const { data: categories } = useCategories();

  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(defaultCategoryId);
  const [teamId, setTeamId] = useState<number | null>(defaultTeamId);
  const [meetingUrl, setMeetingUrl] = useState("");
  const [platform, setPlatform] = useState("");
  const [duration, setDuration] = useState<string>("30");
  const [attendees, setAttendees] = useState("");
  const [description, setDescription] = useState("");
  const [addToCalendar, setAddToCalendar] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Keep defaults in sync when the URL filter changes (e.g. user drilled into
  // a category before opening the form).
  useEffect(() => {
    setCategoryId(defaultCategoryId);
    setTeamId(defaultTeamId);
  }, [defaultCategoryId, defaultTeamId]);

  const selectedCategory = useMemo(
    () => categories.find((c) => c.id === categoryId) ?? null,
    [categories, categoryId],
  );
  const availableTeams = selectedCategory?.teams ?? [];

  const reset = () => {
    setTitle("");
    setScheduledAt("");
    setMeetingUrl("");
    setPlatform("");
    setDuration("30");
    setAttendees("");
    setDescription("");
    setError("");
    // Keep category/team selections + addToCalendar so the next schedule is faster.
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    if (!scheduledAt) {
      setError("Pick a date and time.");
      return;
    }
    if (!teamId) {
      setError("Choose a meeting type and team to schedule under.");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      // datetime-local gives a naive local string; convert to ISO with offset.
      const isoScheduledAt = new Date(scheduledAt).toISOString();
      const attendeeList = attendees
        .split(/[,;\s]+/)
        .map((a) => a.trim())
        .filter((a) => a.length > 0);
      const meeting = await scheduleTeamMeeting(teamId, {
        title: title.trim(),
        scheduled_at: isoScheduledAt,
        meeting_url: meetingUrl.trim() || undefined,
        meeting_platform: platform || undefined,
        duration_minutes: duration ? Number(duration) : undefined,
        description: description.trim() || undefined,
        attendees: attendeeList,
        add_to_calendar: addToCalendar,
      });
      onScheduled(meeting);
      reset();
      setOpen(false);
    } catch (err) {
      console.error("Schedule failed", err);
      setError("Failed to schedule meeting. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const noCategories = categories.length === 0;

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm mb-6 overflow-hidden">
      {/* Toggle bar */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-5 py-4 hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center shrink-0">
            <CalendarPlus className="w-5 h-5 text-indigo-600" />
          </div>
          <div className="text-left min-w-0">
            <h2 className="text-sm font-bold text-slate-900">
              Schedule a meeting
            </h2>
            <p className="text-xs text-slate-500 truncate">
              Plan ahead and bind it to a meeting type and team.
            </p>
          </div>
        </div>
        <ChevronDown
          className={`w-4 h-4 text-slate-500 transition-transform shrink-0 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* Form */}
      {open && (
        <form
          onSubmit={handleSubmit}
          className="border-t border-slate-100 px-5 py-5 grid grid-cols-1 md:grid-cols-12 gap-4"
        >
          {/* Title */}
          <div className="md:col-span-7">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-1.5">
              Title
            </label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Weekly engineering sync"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm"
            />
          </div>

          {/* Date/Time */}
          <div className="md:col-span-5">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Calendar className="w-3 h-3" />
              When
            </label>
            <input
              type="datetime-local"
              required
              min={nowLocalISO()}
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm"
            />
          </div>

          {/* Category */}
          <div className="md:col-span-4">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Tag className="w-3 h-3" />
              Meeting type
            </label>
            <select
              value={categoryId ?? ""}
              onChange={(e) => {
                const v = e.target.value ? Number(e.target.value) : null;
                setCategoryId(v);
                setTeamId(null);
              }}
              disabled={noCategories}
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm disabled:bg-slate-50 disabled:text-slate-400"
            >
              <option value="">Choose a meeting type…</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {noCategories && (
              <p className="mt-1 text-[11px] text-slate-400">
                Create a meeting type first under Categories &amp; Teams.
              </p>
            )}
          </div>

          {/* Team */}
          <div className="md:col-span-4">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Users className="w-3 h-3" />
              Team
            </label>
            <select
              value={teamId ?? ""}
              onChange={(e) =>
                setTeamId(e.target.value ? Number(e.target.value) : null)
              }
              disabled={!selectedCategory || availableTeams.length === 0}
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm disabled:bg-slate-50 disabled:text-slate-400"
            >
              <option value="">
                {!selectedCategory
                  ? "Pick a meeting type first"
                  : availableTeams.length === 0
                  ? "No teams in this type"
                  : "Choose a team…"}
              </option>
              {availableTeams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>

          {/* Duration */}
          <div className="md:col-span-2">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Clock className="w-3 h-3" />
              Duration
            </label>
            <div className="relative">
              <input
                type="number"
                min={5}
                step={5}
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                className="w-full px-3 py-2.5 pr-10 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] font-semibold text-slate-400">
                min
              </span>
            </div>
          </div>

          {/* Platform */}
          <div className="md:col-span-2">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-1.5">
              Platform
            </label>
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm"
            >
              {PLATFORMS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          {/* Meeting URL */}
          <div className="md:col-span-12">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <LinkIcon className="w-3 h-3" />
              Meeting URL{" "}
              <span className="text-slate-400 font-normal normal-case ml-1">
                (optional — leave blank to auto-generate a Google Meet link)
              </span>
            </label>
            <input
              type="url"
              value={meetingUrl}
              onChange={(e) => setMeetingUrl(e.target.value)}
              placeholder="meet.google.com/abc-defg-hij"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm"
            />
          </div>

          {/* Attendees */}
          <div className="md:col-span-12">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Mail className="w-3 h-3" />
              Attendees{" "}
              <span className="text-slate-400 font-normal normal-case ml-1">
                (optional — comma-separated emails)
              </span>
            </label>
            <input
              type="text"
              value={attendees}
              onChange={(e) => setAttendees(e.target.value)}
              placeholder="alice@acme.com, bob@acme.com"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm"
            />
          </div>

          {/* Description */}
          <div className="md:col-span-12">
            <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-1.5">
              Notes{" "}
              <span className="text-slate-400 font-normal normal-case ml-1">
                (optional — sent in the calendar invite)
              </span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Agenda, prep links, anything attendees should see in the invite."
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-sm resize-y"
            />
          </div>

          {/* Calendar toggle */}
          <div className="md:col-span-12 flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg bg-indigo-50/40 border border-indigo-100">
            <label
              htmlFor="add-to-calendar"
              className="flex items-center gap-2 text-xs font-bold text-slate-700 cursor-pointer"
            >
              <CalendarCheck className="w-4 h-4 text-indigo-600" />
              Add to my Google Calendar
              <span className="text-[11px] font-normal text-slate-500 ml-1">
                — sends invites to attendees and auto-creates a Meet link if no
                URL is set.
              </span>
            </label>
            <input
              id="add-to-calendar"
              type="checkbox"
              checked={addToCalendar}
              onChange={(e) => setAddToCalendar(e.target.checked)}
              className="w-4 h-4 accent-indigo-600 cursor-pointer"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="md:col-span-12 px-3 py-2 bg-rose-50 border border-rose-100 text-rose-700 text-xs font-bold rounded-lg">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="md:col-span-12 flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => {
                reset();
                setOpen(false);
              }}
              className="px-4 py-2.5 border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-bold transition-all"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-300 text-white rounded-lg text-sm font-bold shadow-md shadow-indigo-600/20 transition-all active:scale-[0.98]"
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Scheduling…
                </>
              ) : (
                <>
                  <CalendarPlus className="w-4 h-4" />
                  Schedule Meeting
                </>
              )}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
