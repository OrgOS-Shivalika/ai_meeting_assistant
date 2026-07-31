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
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogBody,
  DialogFooter,
  DialogHeader,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { IconChip } from "@/components/ui/icon-chip";
import { SearchInput } from "@/components/ui/input";
import { PageContainer, PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { tint } from "@/lib/vibrant";
import { cn } from "@/lib/utils";

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

/** One brand hue per report category — cycled, never repeated in a row. */
const CATEGORY_HUE: Record<string, string> = {
  productivity: "var(--vb-info)",
  engagement: "var(--vb-success)",
  decisions: "var(--vb-lavender)",
  compliance: "var(--vb-ochre)",
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
      <PageContainer width="default">
        <PageHeader
          eyebrow="Workspace"
          title="Reports"
          description="Meeting and task analytics across the org — engagement, decision velocity and follow-through."
          actions={
            <Button>
              <BarChart3 />
              Generate report
            </Button>
          }
        />

        {/* Filters */}
        <div className="mb-6 flex flex-col gap-3 sm:flex-row">
          <SearchInput
            icon={Search}
            placeholder="Search reports…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            wrapperClassName="flex-1"
            className="h-10"
          />
          <Select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value as any)}
            className="h-10 sm:w-48"
          >
            <option value="all">All categories</option>
            <option value="productivity">Productivity</option>
            <option value="engagement">Engagement</option>
            <option value="decisions">Decisions</option>
            <option value="compliance">Compliance</option>
          </Select>
          <Select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="h-10 sm:w-40"
          >
            <option value="recent">Most recent</option>
            <option value="title">Title (A–Z)</option>
          </Select>
        </div>

        {/* Reports grid */}
        {filtered.length === 0 ? (
          <EmptyState
            icon={BarChart3}
            color="var(--vb-info)"
            title="No reports found"
            description={
              search
                ? "Try adjusting your search or filters."
                : "Generate your first report to get started."
            }
          />
        ) : (
          <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
            {filtered.map((report) => {
              const Icon = CATEGORY_ICONS[report.category];
              const hue = CATEGORY_HUE[report.category];

              return (
                <Card
                  key={report.id}
                  variant="default"
                  className="cursor-pointer overflow-hidden rounded-xl transition-colors hover:border-muted-soft"
                  onClick={() => setSelectedReport(report)}
                >
                  {/* Saturated band header — the one hue per card. */}
                  <div
                    className="flex h-24 items-center gap-3.5 px-6"
                    style={{ background: tint(hue, 12) }}
                  >
                    <Icon className="size-7 shrink-0" style={{ color: hue }} />
                    <div className="min-w-0 flex-1">
                      <h3 className="vb-title-md truncate text-[17px]">
                        {report.title}
                      </h3>
                      <p className="mt-0.5 truncate text-xs text-muted-ink">
                        {report.description}
                      </p>
                    </div>
                  </div>

                  {/* Metrics */}
                  <div className="space-y-3 p-5">
                    {report.metrics.slice(0, 2).map((metric, idx) => (
                      <div key={idx} className="flex items-center justify-between">
                        <span className="text-[13px] text-muted-ink">
                          {metric.label}
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm font-medium text-ink">
                            {metric.value}
                          </span>
                          {metric.change !== undefined && metric.change !== 0 && (
                            <span
                              className={cn(
                                "font-mono text-[11px] font-semibold",
                                metric.trend === "up"
                                  ? "text-success"
                                  : metric.trend === "down"
                                    ? "text-error"
                                    : "text-muted-ink",
                              )}
                            >
                              {metric.trend === "up"
                                ? "↑"
                                : metric.trend === "down"
                                  ? "↓"
                                  : "→"}
                              {Math.abs(metric.change)}%
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                    {report.metrics.length > 2 && (
                      <p className="border-t border-hairline-soft pt-3 text-xs text-muted-soft">
                        +{report.metrics.length - 2} more metrics
                      </p>
                    )}
                  </div>

                  {/* Footer */}
                  <div className="flex items-center justify-between border-t border-hairline-soft bg-surface-soft px-5 py-3.5 text-xs text-muted-ink">
                    <span className="font-mono">{report.dateRange}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDownload(report);
                      }}
                      className="rounded-xs p-1.5 text-muted-soft transition-colors hover:bg-canvas hover:text-ink"
                      title="Download report"
                    >
                      <Download className="size-3.5" />
                    </button>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </PageContainer>

      {/* Report detail */}
      <Dialog
        open={!!selectedReport}
        onClose={() => setSelectedReport(null)}
        size="lg"
      >
        {selectedReport && (
          <>
            <DialogHeader
              title={selectedReport.title}
              description={selectedReport.description}
              onClose={() => setSelectedReport(null)}
              icon={
                <IconChip
                  size="lg"
                  color={CATEGORY_HUE[selectedReport.category]}
                >
                  {(() => {
                    const Icon = CATEGORY_ICONS[selectedReport.category];
                    return <Icon />;
                  })()}
                </IconChip>
              }
            />
            <DialogBody className="space-y-6">
              {/* Report meta */}
              <div className="flex flex-wrap items-center gap-6 text-[13px] text-muted-ink">
                <span className="inline-flex items-center gap-2">
                  <Calendar className="size-4 text-muted-soft" />
                  {selectedReport.dateRange}
                </span>
                <span className="inline-flex items-center gap-2">
                  <Clock className="size-4 text-muted-soft" />
                  Generated{" "}
                  {new Date(selectedReport.createdDate).toLocaleDateString()}
                </span>
              </div>

              {/* Metrics grid */}
              <div className="space-y-3.5">
                <h3 className="vb-label-caps">Metrics</h3>
                <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                  {selectedReport.metrics.map((metric, idx) => (
                    <div
                      key={idx}
                      className="rounded-lg border border-hairline bg-surface-soft p-4"
                    >
                      <p className="text-xs text-muted-ink">{metric.label}</p>
                      <div className="mt-2 flex items-baseline gap-2.5">
                        <p className="font-mono text-2xl leading-none font-medium text-ink">
                          {metric.value}
                        </p>
                        {metric.change !== undefined && metric.change !== 0 && (
                          <span
                            className={cn(
                              "font-mono text-[13px] font-semibold",
                              metric.trend === "up"
                                ? "text-success"
                                : metric.trend === "down"
                                  ? "text-error"
                                  : "text-muted-ink",
                            )}
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
            </DialogBody>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setSelectedReport(null)}
              >
                Close
              </Button>
              <Button onClick={() => handleDownload(selectedReport)}>
                <Download />
                Download
              </Button>
            </DialogFooter>
          </>
        )}
      </Dialog>
    </Layout>
  );
}
