// Phase 7G — typed HTTP wrappers for the Agent Control Dashboard.
//
// All functions delegate to `apiClient` (which handles auth + 401
// redirects). The shapes returned here mirror the backend's Pydantic
// response models verbatim — see `app/schemas/agent_api_schema.py`.

import { apiClient } from "../../services/apiClient";
import type {
  AgentProfile,
  AgentPromptConfig,
  AgentSummaryRow,
  AgentTypeDescriptor,
  AgentVersionMetricRow,
  EvalRunDetail,
  EvalRunSummary,
  ModularPrompt,
  PromptDeployment,
  PromptVersion,
  PromptVersionSummary,
  ToolDescriptor,
  VersionDiff,
} from "./types";

// ---------------------------------------------------------------------------
// Agent profile CRUD
// ---------------------------------------------------------------------------

export function listAgentTypes(): Promise<AgentTypeDescriptor[]> {
  return apiClient("/agents/types");
}

export function listAgents(params?: {
  agent_type?: string;
  status?: "active" | "archived";
  limit?: number;
}): Promise<AgentProfile[]> {
  const q = new URLSearchParams();
  if (params?.agent_type) q.set("agent_type", params.agent_type);
  if (params?.status) q.set("status", params.status);
  if (params?.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiClient(`/agents${qs ? `?${qs}` : ""}`);
}

export function getAgent(profileId: string): Promise<AgentProfile> {
  return apiClient(`/agents/${profileId}`);
}

export function createAgent(payload: {
  slug: string;
  display_name: string;
  agent_type: string;
  description?: string;
  default_modular_prompt?: ModularPrompt;
  eval_gate_required?: boolean;
  eval_min_score?: number | null;
}): Promise<AgentProfile> {
  return apiClient("/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function patchAgent(
  profileId: string,
  payload: Partial<{
    display_name: string;
    description: string;
    default_modular_prompt: ModularPrompt;
    eval_gate_required: boolean;
    eval_min_score: number | null;
  }>,
): Promise<AgentProfile> {
  return apiClient(`/agents/${profileId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function archiveAgent(profileId: string): Promise<AgentProfile> {
  return apiClient(`/agents/${profileId}/archive`, { method: "POST" });
}

export function duplicateAgent(
  profileId: string,
  payload: { new_slug: string; new_display_name: string },
): Promise<AgentProfile> {
  return apiClient(`/agents/${profileId}/duplicate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Prompt configs (scope bindings) + versions
// ---------------------------------------------------------------------------

export function listPromptConfigs(params?: {
  agent_profile_id?: string;
  scope_type?: string;
  status?: "active" | "archived";
}): Promise<AgentPromptConfig[]> {
  const q = new URLSearchParams();
  if (params?.agent_profile_id) q.set("agent_profile_id", params.agent_profile_id);
  if (params?.scope_type) q.set("scope_type", params.scope_type);
  if (params?.status) q.set("status", params.status);
  const qs = q.toString();
  return apiClient(`/prompt-configs${qs ? `?${qs}` : ""}`);
}

export function createPromptConfig(payload: {
  agent_profile_id: string;
  scope_type: "organization" | "category" | "team";
  scope_id?: number | null;
}): Promise<AgentPromptConfig> {
  return apiClient("/prompt-configs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function archivePromptConfig(configId: string): Promise<AgentPromptConfig> {
  return apiClient(`/prompt-configs/${configId}/archive`, { method: "POST" });
}

export function listVersions(
  configId: string,
  params?: { state?: "draft" | "published" | "archived"; limit?: number },
): Promise<PromptVersionSummary[]> {
  const q = new URLSearchParams();
  if (params?.state) q.set("state", params.state);
  if (params?.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiClient(
    `/prompt-configs/${configId}/versions${qs ? `?${qs}` : ""}`,
  );
}

export function getVersion(
  configId: string,
  versionId: string,
): Promise<PromptVersion> {
  return apiClient(`/prompt-configs/${configId}/versions/${versionId}`);
}

export function createVersion(
  configId: string,
  payload: {
    label?: string | null;
    modular_prompt?: ModularPrompt;
    retrieval_config?: Record<string, unknown>;
    model_config_payload?: Record<string, unknown>;
    tool_permissions?: { allowed: string[]; denied: string[] };
    meta?: Record<string, unknown>;
  },
): Promise<PromptVersion> {
  return apiClient(`/prompt-configs/${configId}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function patchVersion(
  configId: string,
  versionId: string,
  payload: Partial<{
    label: string | null;
    modular_prompt: ModularPrompt;
    retrieval_config: Record<string, unknown>;
    model_config_payload: Record<string, unknown>;
    tool_permissions: { allowed: string[]; denied: string[] };
    meta: Record<string, unknown>;
  }>,
): Promise<PromptVersion> {
  return apiClient(`/prompt-configs/${configId}/versions/${versionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function publishVersion(
  configId: string,
  versionId: string,
  reason?: string,
): Promise<PromptVersion> {
  return apiClient(
    `/prompt-configs/${configId}/versions/${versionId}/publish`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
}

export function rollbackConfig(
  configId: string,
  toVersionId: string,
  reason?: string,
): Promise<PromptVersion> {
  return apiClient(`/prompt-configs/${configId}/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      to_version_id: toVersionId,
      reason: reason ?? null,
    }),
  });
}

export function archiveVersion(
  configId: string,
  versionId: string,
): Promise<PromptVersion> {
  return apiClient(
    `/prompt-configs/${configId}/versions/${versionId}/archive`,
    { method: "POST" },
  );
}

export function diffVersions(
  configId: string,
  fromVersionId: string,
  toVersionId: string,
): Promise<VersionDiff> {
  return apiClient(
    `/prompt-configs/${configId}/versions/${fromVersionId}/diff?against=${toVersionId}`,
  );
}

export function listDeployments(
  configId: string,
  limit = 50,
): Promise<PromptDeployment[]> {
  return apiClient(
    `/prompt-configs/${configId}/deployments?limit=${limit}`,
  );
}

// ---------------------------------------------------------------------------
// Observability
// ---------------------------------------------------------------------------

export function fetchAgentsSummary(days = 30): Promise<AgentSummaryRow[]> {
  return apiClient(`/rag/observability/agents?days=${days}`);
}

export function fetchAgentDetail(
  profileId: string,
  days = 30,
): Promise<AgentSummaryRow & {
  agent_profile_id: string;
  slug: string;
  display_name: string;
  status: string;
}> {
  return apiClient(
    `/rag/observability/agents/${profileId}?days=${days}`,
  );
}

export function fetchAgentVersionMetrics(
  profileId: string,
  days = 30,
): Promise<AgentVersionMetricRow[]> {
  return apiClient(
    `/rag/observability/agents/${profileId}/versions?days=${days}`,
  );
}

// ---------------------------------------------------------------------------
// Tools + eval
// ---------------------------------------------------------------------------

export function listToolCatalog(): Promise<ToolDescriptor[]> {
  return apiClient("/agents/tools/catalog");
}

export function listEvalRuns(profileId: string): Promise<EvalRunSummary[]> {
  return apiClient(`/agents/${profileId}/eval/runs`);
}

export function triggerEvalRun(
  profileId: string,
  payload?: { prompt_version_id?: string; mode?: "stub" | "real"; threshold?: number },
): Promise<EvalRunDetail> {
  return apiClient(`/agents/${profileId}/eval/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: payload?.mode ?? "stub",
      threshold: payload?.threshold ?? 0.8,
      prompt_version_id: payload?.prompt_version_id ?? null,
    }),
  });
}

// ---------------------------------------------------------------------------
// Playground (SSE — manual parser, same pattern as features/ask)
// ---------------------------------------------------------------------------

export type PlaygroundEvent =
  | { event: "plan"; data: Record<string, unknown> }
  | { event: "retrieved"; data: Record<string, unknown> }
  | { event: "token"; data: { text: string } }
  | { event: "citations"; data: { citations: unknown[] } }
  | { event: "done"; data: Record<string, unknown> }
  | { event: "error"; data: { message: string; detail?: string } };

export async function* streamPlayground(payload: {
  query_text: string;
  scope_type?: "team" | "category" | "global" | null;
  scope_id?: number | null;
  agent_profile_slug?: string | null;
  agent_profile_id?: string | null;
  inline_overrides?: {
    modular_prompt?: ModularPrompt;
    retrieval_config?: Record<string, unknown>;
    model_config_payload?: Record<string, unknown>;
    tool_permissions?: { allowed: string[]; denied: string[] };
  } | null;
}): AsyncIterable<PlaygroundEvent> {
  const token = localStorage.getItem("token");
  const base = (import.meta as any).env.VITE_API_URL || "";
  const res = await fetch(
    `${base.replace(/\/$/, "")}/agent-playground/run`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Playground failed (${res.status}): ${body}`);
  }
  if (!res.body) {
    throw new Error("Playground response had no body");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Same pattern as
    // features/ask/hooks/useChatStream.ts.
    let idx = buf.indexOf("\n\n");
    while (idx !== -1) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      idx = buf.indexOf("\n\n");

      let eventName = "message";
      let dataLine = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
      }
      if (dataLine) {
        try {
          const data = JSON.parse(dataLine);
          yield { event: eventName, data } as PlaygroundEvent;
        } catch {
          // ignore malformed frame
        }
      }
    }
  }
}
