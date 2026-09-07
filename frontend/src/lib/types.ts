/**
 * Die Antwortformen des Backends.
 *
 * Hier von Hand gepflegt, solange es wenige sind. Sobald die API breiter
 * wird, werden sie aus der OpenAPI-Ausgabe erzeugt — das ist einer der
 * Gruende fuer FastAPI (Kapitel 3).
 */

export interface HealthResponse {
  status: string;
  version: string;
  database_revision: string | null;
}

export interface SdeBuildInfo {
  build: string;
  source_url: string;
  completed_at: string | null;
  row_counts: Record<string, number>;
}

export interface RateLimitGroupInfo {
  limit: number;
  remaining: number;
  window_seconds: number;
  blocked_seconds_left: number;
}

export interface RateLimitInfo {
  error_remain: number | null;
  breaker_seconds_left: number;
  groups: Record<string, RateLimitGroupInfo>;
}

export interface CompatibilityInfo {
  date: string;
  age_days: number;
  guaranteed_days: number;
  state: "ok" | "warn" | "expired";
}

export interface SyncRunInfo {
  id: number;
  route: string;
  owner_type: string;
  owner_id: number | null;
  started_at: string;
  duration_ms: number | null;
  status_code: number | null;
  unchanged: boolean;
  tokens_spent: number;
  rows_written: number;
  error: string | null;
}

export interface StatusResponse {
  version: string;
  database_revision: string | null;
  database_path: string;
  sde: SdeBuildInfo | null;
  compatibility: CompatibilityInfo;
  rate_limit: RateLimitInfo;
  recent_syncs: SyncRunInfo[];
}
