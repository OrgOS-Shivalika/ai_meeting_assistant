import { apiClient } from "../../services/apiClient";

export interface ClientCard {
  id: number;
  name: string;
  team_id: number | null;
  stage: string;
  board_version: number;
  calls_in_stage: number | null;
  stall_flags: unknown[];
  latest_recommendation: { recommended_stage: string; rationale: string } | null;
  updated_at: string;
}

export interface ClientDetail extends ClientCard {
  board: Record<string, unknown> | null;
}

export interface BoardResponse {
  stages: string[];
  clients: ClientCard[];
}

export interface CCRun {
  id: number;
  client_id: number;
  meeting_id: number | null;
  mode: "process" | "brief";
  model: string;
  status: string;
  package_markdown: string | null;
  board_version_after: number | null;
  stage_recommendation: { recommended_stage: string; rationale: string } | null;
  error_message: string | null;
  duration_ms: number | null;
  created_at: string;
}

const json = (method: string, payload?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}),
});

export const fetchBoard = (): Promise<BoardResponse> => apiClient("/continuum/clients");

export const createClient = (name: string): Promise<ClientCard> =>
  apiClient("/continuum/clients", json("POST", { name }));

export const getClient = (id: number): Promise<ClientDetail> =>
  apiClient(`/continuum/clients/${id}`);

export const deleteClient = (id: number): Promise<{ ok: boolean }> =>
  apiClient(`/continuum/clients/${id}`, json("DELETE"));

export const confirmStage = (id: number, stage: string): Promise<ClientCard> =>
  apiClient(`/continuum/clients/${id}/stage`, json("PATCH", { stage }));

export const processManual = (
  id: number,
  payload: { raw_input: string; attendees?: string[]; agenda?: string[]; ideal_outcome?: string },
): Promise<CCRun> => apiClient(`/continuum/clients/${id}/process`, json("POST", payload));

export const briefClient = (
  id: number,
  payload: { agenda?: string[]; ideal_outcome?: string } = {},
): Promise<CCRun> => apiClient(`/continuum/clients/${id}/brief`, json("POST", payload));

export const listRuns = (id: number): Promise<CCRun[]> =>
  apiClient(`/continuum/clients/${id}/runs`);
