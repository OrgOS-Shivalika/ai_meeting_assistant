import { apiClient } from "../../../services/apiClient";

export type HarnessRunSummary = {
  run_id: string;
  skill_id: string | null;
  meeting_id: number | null;
  meeting_title: string | null;
  tool_calls: number;
  ok: number;
  failed: number;
  // True/false when a `_skill_run` sentinel row exists for this run
  // (every skill written via graph_orchestrator). null for runs
  // predating that change.
  skill_success: boolean | null;
  total_duration_ms: number;
  total_tokens: number;
  iterations: number;
  started_at: string;
  ended_at: string;
};

export type HarnessInvocation = {
  id: number;
  iteration: number;
  tool_name: string;
  args: Record<string, unknown> | null;
  result: unknown;
  success: boolean;
  error_message: string | null;
  duration_ms: number | null;
  tokens_used: number | null;
  created_at: string;
};

export type HarnessRunDetail = HarnessRunSummary & {
  invocations: HarnessInvocation[];
};

export type HarnessMetricsPerSkill = {
  skill_id: string;
  runs: number;
  ok: number;
  failed: number;
  success_rate: number | null;
  total_tokens: number;
  avg_tokens: number | null;
  p50_duration_ms: number | null;
  p95_duration_ms: number | null;
  avg_duration_ms: number | null;
  retry_storms: number;
};

export type HarnessMetricsTopFailure = {
  error: string;
  count: number;
  last_seen: string;
};

export type HarnessMetrics = {
  window_days: number;
  totals: {
    skill_runs: number;
    skill_runs_ok: number;
    skill_runs_failed: number;
    success_rate: number | null;
    total_tokens: number;
    avg_duration_ms: number | null;
    retry_storm_runs: number;
  };
  per_skill: HarnessMetricsPerSkill[];
  top_failures: HarnessMetricsTopFailure[];
};

export const harnessApi = {
  metrics: (days = 30): Promise<HarnessMetrics> =>
    apiClient(`/harness/metrics?days=${days}`),
  listRuns: (params: { days?: number; skill_id?: string; meeting_id?: number; limit?: number } = {}): Promise<HarnessRunSummary[]> => {
    const qs = new URLSearchParams();
    if (params.days) qs.set("days", String(params.days));
    if (params.skill_id) qs.set("skill_id", params.skill_id);
    if (params.meeting_id) qs.set("meeting_id", String(params.meeting_id));
    if (params.limit) qs.set("limit", String(params.limit));
    const s = qs.toString();
    return apiClient(`/harness/runs${s ? "?" + s : ""}`);
  },
  runDetail: (runId: string): Promise<HarnessRunDetail> =>
    apiClient(`/harness/runs/${runId}`),
};
