import { useState, useMemo } from "react";
import {
  Search,
  BarChart3,
  Download,
  Calendar,
  Users,
  CheckCircle2,
  Clock,
  AlertCircle,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";

interface ReportMetric {
  label: string;
  value: string | number;
  change?: number;
  trend?: "up" | "down" | "neutral";
}

interface Report {
  id: number;
  title: string;
  description: string;
  category: "productivity" | "engagement" | "decisions" | "compliance";
  dateRange: string;
  createdDate: string;
  metrics: ReportMetric[];
}

const MOCK_REPORTS: Report[] = [
  {
    id: 1,
    title: "June Meeting Summary",
    description: "Overview of all meetings held in June",
    category: "productivity",
    dateRange: "June 1 - June 30, 2024",
    createdDate: "2024-06-02",
    metrics: [
      { label: "Total Meetings", value: 127, change: 15, trend: "up" },
      { label: "Avg Duration", value: "45 min", change: -5, trend: "down" },
      { label: "Participants", value: 342, change: 28, trend: "up" },
      { label: "Action Items", value: 234, change: 12, trend: "up" },
    ],
  },
  {
    id: 2,
    title: "Team Engagement Report",
    description: "Analysis of team member participation and engagement",
    category: "engagement",
    dateRange: "May 1 - May 31, 2024",
    createdDate: "2024-06-01",
    metrics: [
      { label: "Active Members", value: 24, change: 3, trend: "up" },
      { label: "Avg Meetings per Member", value: 5.2, change: 0.8, trend: "up" },
      { label: "Engagement Score", value: "8.5/10", change: 0.5, trend: "up" },
      { label: "Decision Velocity", value: 156, change: 12, trend: "up" },
    ],
  },
  {
    id: 3,
    title: "Decision Tracking Q2",
    description: "Quarterly review of decisions made and tracked",
    category: "decisions",
    dateRange: "April 1 - June 30, 2024",
    createdDate: "2024-06-02",
    metrics: [
      { label: "Decisions Made", value: 487, change: 89, trend: "up" },
      { label: "Avg Decision Time", value: "2.3 days", change: -0.4, trend: "down" },
      { label: "Implementation Rate", value: "94%", change: 5, trend: "up" },
      { label: "Stakeholder Alignment", value: "91%", change: 3, trend: "up" },
    ],
  },
  {
    id: 4,
    title: "Compliance Audit Report",
    description: "Meeting compliance and data governance review",
    category: "compliance",
    dateRange: "June 1 - June 30, 2024",
    createdDate: "2024-05-31",
    metrics: [
      { label: "Meetings Recorded", value: "100%", change: 0, trend: "neutral" },
      { label: "Transcripts Archived", value: "99%", change: 1, trend: "up" },
      { label: "PII Detected & Flagged", value: 23, change: -5, trend: "down" },
      { label: "Compliance Score", value: "96%", change: 2, trend: "up" },
    ],
  },
  {
    id: 5,
    title: "May Monthly Report",
    description: "Comprehensive monthly review for stakeholders",
    category: "productivity",
    dateRange: "May 1 - May 31, 2024",
    createdDate: "2024-05-30",
    metrics: [
      { label: "Total Meetings", value: 112, change: -12, trend: "down" },
      { label: "Avg Duration", value: "48 min", change: 3, trend: "up" },
      { label: "Participants", value: 315, change: -18, trend: "down" },
      { label: "Action Items", value: 201, change: -28, trend: "down" },
    ],
  },
];

const CATEGORY_COLORS: Record<string, string> = {
  productivity: "bg-blue-50 text-blue-700 border-blue-200",
  engagement: "bg-emerald-50 text-emerald-700 border-emerald-200",
  decisions: "bg-purple-50 text-purple-700 border-purple-200",
  compliance: "bg-amber-50 text-amber-700 border-amber-200",
};

const CATEGORY_ICONS: Record<string, any> = {
  productivity: BarChart3,
  engagement: Users,
  decisions: CheckCircle2,
  compliance: AlertCircle,
};

export default function ReportsPage() {
  const [reports] = useState<Report[]>(MOCK_REPORTS);
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState<"all" | "productivity" | "engagement" | "decisions" | "compliance">("all");
  const [sortBy, setSortBy] = useState<"recent" | "title">("recent");
  const [selectedReport, setSelectedReport] = useState<Report | null>(null);

  const filtered = useMemo(() => {
    let rows = reports;

    if (filterCategory !== "all") {
      rows = rows.filter((r) => r.category === filterCategory);
    }

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (r) =>
          r.title.toLowerCase().includes(q) ||
          r.description.toLowerCase().includes(q),
      );
    }

    if (sortBy === "recent") {
      rows = rows.sort((a, b) => new Date(b.createdDate).getTime() - new Date(a.createdDate).getTime());
    } else {
      rows = rows.sort((a, b) => a.title.localeCompare(b.title));
    }

    return rows;
  }, [reports, filterCategory, search, sortBy]);

  const handleDownload = (report: Report) => {
    // Mock download functionality
    const dataStr = JSON.stringify(report, null, 2);
    const element = document.createElement("a");
    element.setAttribute("href", "data:text/plain;charset=utf-8," + encodeURIComponent(dataStr));
    element.setAttribute("download", `${report.title}.json`);
    element.style.display = "none";
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-2 py-4">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-[#0F1523] tracking-tight">Reports</h1>
            <p className="text-xs text-[#777681] mt-0.5">
              Generate and track insights about your meetings, team engagement, and organizational decisions.
            </p>
          </div>
          <button
            className="flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm active:scale-95"
          >
            <BarChart3 className="w-4 h-4" />
            Generate Report
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-col sm:flex-row gap-3 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search reports..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 pr-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none w-full"
            />
          </div>

          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value as any)}
            className="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none flex items-center gap-2"
          >
            <option value="all">All Categories</option>
            <option value="productivity">Productivity</option>
            <option value="engagement">Engagement</option>
            <option value="decisions">Decisions</option>
            <option value="compliance">Compliance</option>
          </select>

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
          >
            <option value="recent">Most Recent</option>
            <option value="title">Title (A-Z)</option>
          </select>
        </div>

        {/* Reports Grid */}
        {filtered.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-lg border border-gray-200">
            <div className="w-14 h-14 bg-indigo-50 rounded-md flex items-center justify-center mx-auto mb-3">
              <BarChart3 className="w-7 h-7 text-indigo-500" />
            </div>
            <h3 className="text-lg font-bold text-[#0F1523] mb-1">No reports found</h3>
            <p className="text-[#777681] max-w-xs mx-auto text-sm">
              {search ? "Try adjusting your search or filters" : "Generate your first report to get started"}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((report) => {
              const Icon = CATEGORY_ICONS[report.category];
              const categoryColor = CATEGORY_COLORS[report.category];

              return (
                <div
                  key={report.id}
                  className="bg-white border border-gray-200 rounded-lg overflow-hidden hover:shadow-lg transition-shadow cursor-pointer group"
                  onClick={() => setSelectedReport(report)}
                >
                  {/* Header */}
                  <div className={`px-4 py-3 border-b border-gray-100 flex items-start justify-between ${categoryColor}`}>
                    <div className="flex items-start gap-2 flex-1 min-w-0">
                      <Icon className="w-4 h-4 mt-0.5 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <h3 className="font-bold text-sm truncate">{report.title}</h3>
                        <p className="text-xs mt-0.5 opacity-75">{report.description}</p>
                      </div>
                    </div>
                  </div>

                  {/* Metrics */}
                  <div className="p-4 space-y-3">
                    {report.metrics.slice(0, 2).map((metric, idx) => (
                      <div key={idx} className="flex items-center justify-between">
                        <span className="text-xs text-[#777681] font-medium">{metric.label}</span>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-sm text-[#0F1523]">{metric.value}</span>
                          {metric.change !== undefined && metric.change !== 0 && (
                            <span
                              className={`text-xs font-semibold ${
                                metric.trend === "up"
                                  ? "text-emerald-600"
                                  : metric.trend === "down"
                                  ? "text-red-600"
                                  : "text-slate-500"
                              }`}
                            >
                              {metric.trend === "up" ? "↑" : metric.trend === "down" ? "↓" : "→"}
                              {Math.abs(metric.change)}%
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                    {report.metrics.length > 2 && (
                      <p className="text-xs text-[#777681] italic pt-2 border-t border-gray-100">
                        +{report.metrics.length - 2} more metrics
                      </p>
                    )}
                  </div>

                  {/* Footer */}
                  <div className="px-4 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between text-xs text-[#777681]">
                    <span>{report.dateRange}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDownload(report);
                      }}
                      className="p-1.5 hover:bg-white rounded transition-colors text-slate-400 hover:text-indigo-600"
                      title="Download report"
                    >
                      <Download className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Report Detail Modal */}
      {selectedReport && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            {/* Modal Header */}
            <div className={`sticky top-0 ${CATEGORY_COLORS[selectedReport.category]} px-6 py-4 border-b border-gray-200 flex items-start justify-between`}>
              <div className="flex-1 min-w-0">
                <h2 className="text-xl font-bold mb-1">{selectedReport.title}</h2>
                <p className="text-sm opacity-75">{selectedReport.description}</p>
              </div>
              <button
                onClick={() => setSelectedReport(null)}
                className="ml-4 text-lg font-bold opacity-50 hover:opacity-100"
              >
                ✕
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 space-y-6">
              {/* Report Meta */}
              <div className="flex items-center gap-6 flex-wrap text-sm text-[#777681]">
                <div className="flex items-center gap-2">
                  <Calendar className="w-4 h-4" />
                  <span>{selectedReport.dateRange}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4" />
                  <span>Generated {new Date(selectedReport.createdDate).toLocaleDateString()}</span>
                </div>
              </div>

              {/* Metrics Grid */}
              <div className="space-y-4">
                <h3 className="text-sm font-bold text-[#0F1523] uppercase tracking-wide">Metrics</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {selectedReport.metrics.map((metric, idx) => (
                    <div key={idx} className="bg-slate-50 border border-gray-200 rounded-lg p-4">
                      <p className="text-xs text-[#777681] font-semibold mb-2">{metric.label}</p>
                      <div className="flex items-baseline gap-2">
                        <p className="text-2xl font-bold text-[#0F1523]">{metric.value}</p>
                        {metric.change !== undefined && metric.change !== 0 && (
                          <span
                            className={`text-sm font-semibold ${
                              metric.trend === "up"
                                ? "text-emerald-600"
                                : metric.trend === "down"
                                ? "text-red-600"
                                : "text-slate-500"
                            }`}
                          >
                            {metric.trend === "up" && "↑"}
                            {metric.trend === "down" && "↓"}
                            {metric.trend === "neutral" && "→"}
                            {Math.abs(metric.change)}%
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-3 pt-4 border-t border-gray-200">
                <button
                  onClick={() => handleDownload(selectedReport)}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors"
                >
                  <Download className="w-4 h-4" />
                  Download
                </button>
                <button
                  onClick={() => setSelectedReport(null)}
                  className="flex-1 px-4 py-2.5 border border-gray-200 hover:bg-gray-50 text-slate-700 rounded-lg text-sm font-semibold transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
