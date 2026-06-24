import { apiClient } from "../../../services/apiClient";

export type HarnessRunSummary = {
  run_id: string;
  skill_id: string | null;
  meeting_id: number | null;
  meeting_title: string | null;
  tool_calls: number;
  ok: number;
  failed: number;
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

export const harnessApi = {
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
