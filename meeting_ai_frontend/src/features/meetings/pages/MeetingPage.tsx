import Layout from "../../../shared/components/Layout";
import { useMeetings } from "../hooks/useMeetings";
import { useCategories } from "../hooks/useCategories";
import MeetingRow from "../components/MeetingRow";
import { ChevronLeft, LayoutGrid, List } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import MeetingList from "../components/MeetingList";
import { deleteMeeting } from "../api";

export default function MeetingsPage() {
  const [searchParams] = useSearchParams();
  const categoryId = searchParams.get("category_id");
  const teamId = searchParams.get("team_id");

  const filter = useMemo(
    () => ({
      category_id: categoryId ? Number(categoryId) : null,
      team_id: teamId ? Number(teamId) : null,
    }),
    [categoryId, teamId],
  );

  const { data, loading, removeMeeting } = useMeetings(filter);
  const { data: categories } = useCategories();
  const [view, setView] = useState<"table" | "grid">("table");
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const activeCategory = filter.category_id
    ? categories.find((c) => c.id === filter.category_id) ?? null
    : null;
  const activeTeam = filter.team_id
    ? activeCategory?.teams?.find((t) => t.id === filter.team_id) ?? null
    : null;
  const headerTitle = activeTeam
    ? `${activeCategory?.name} · ${activeTeam.name}`
    : activeCategory
    ? activeCategory.name
    : "Meetings";

  const handleDelete = async (id: number) => {
    if (!window.confirm("Delete this meeting? This cannot be undone.")) return;
    setDeletingId(id);
    try {
      await deleteMeeting(id);
      removeMeeting(id);
    } catch (err) {
      console.error("Delete failed", err);
      alert("Failed to delete meeting. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
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

  if (!data || data.length === 0) {
    const emptyMessage = activeCategory
      ? activeTeam
        ? `No meetings in ${activeTeam.name} yet.`
        : `No meetings in ${activeCategory.name} yet.`
      : "You haven't added any meetings yet.";
    return (
      <Layout>
        <div className="max-w-7xl mx-auto px-2 py-4">
          <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
            <div className="w-14 h-14 bg-[#EEF2FF] rounded-md flex items-center justify-center mx-auto mb-3">
              <svg className="w-7 h-7 text-[#4F46E5]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
              </svg>
            </div>
            <h3 className="text-lg font-bold text-[#0F1523] mb-1">No meetings found</h3>
            <p className="text-[#777681] max-w-xs mx-auto text-sm">{emptyMessage}</p>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-2 py-4">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <div
              className="p-1.5 rounded-md"
              style={{
                backgroundColor: activeCategory?.color
                  ? `${activeCategory.color}1A`
                  : "#EEF2FF",
              }}
            >
              <ChevronLeft
                className="w-4 h-4"
                style={{ color: activeCategory?.color || "#4F46E5" }}
              />
            </div>
            <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">{headerTitle}</h1>
            <span className="text-xs font-medium text-[#777681] ml-2">
              {data.length} sessions
            </span>
          </div>

          <div className="flex items-center gap-1.5 bg-gray-100 p-1 rounded-lg self-start">
            <button
              onClick={() => setView("table")}
              className={`p-1.5 rounded transition-all ${
                view === "table"
                  ? "bg-white text-[#4F46E5] shadow-sm"
                  : "text-[#777681] hover:text-[#0F1523]"
              }`}
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => setView("grid")}
              className={`p-1.5 rounded transition-all ${
                view === "grid"
                  ? "bg-white text-[#4F46E5] shadow-sm"
                  : "text-[#777681] hover:text-[#0F1523]"
              }`}
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
          </div>
        </div>

        {view === "table" ? (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50/50 border-b border-gray-100">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                    Source
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                    Meeting Details
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                    Timestamp
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                    Participants
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-[#777681] uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-[#777681] uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.map((meeting) => (
                  <MeetingRow
                    key={meeting.id}
                    meeting={meeting}
                    onDelete={handleDelete}
                    isDeleting={deletingId === meeting.id}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <MeetingList
            meetings={data}
            onDelete={handleDelete}
            deletingId={deletingId}
          />
        )}
      </div>
    </Layout>
  );
}