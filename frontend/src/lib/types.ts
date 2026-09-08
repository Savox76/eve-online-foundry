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
  data_dir: string;
  portable: boolean;
  sde: SdeBuildInfo | null;
  compatibility: CompatibilityInfo;
  rate_limit: RateLimitInfo;
  recent_syncs: SyncRunInfo[];
}

// ---------------------------------------------------------------------------
// Anmeldung und Charaktere
// ---------------------------------------------------------------------------

export interface ScopeTierInfo {
  tier: string;
  label: string;
  description: string;
  scopes: string[];
  required_roles: Record<string, string>;
}

export interface LoginStartResponse {
  id: string;
  url: string;
}

export interface LoginStatusResponse {
  id: string;
  state: "waiting" | "done" | "failed";
  character_id: number | null;
  character_name: string;
  error: string | null;
  started_at: string;
}

export interface CharacterInfo {
  character_id: number;
  name: string;
  corporation_id: number | null;
  alliance_id: number | null;
  status: string;
  status_reason: string | null;
  connected_at: string;
  last_seen_at: string | null;
  scopes: string[];
  token_storage: string;
  access_expires_at: string | null;
  last_refresh_at: string | null;
  roles: string[];
  /** Erteilte Corp-Scopes, denen die passende In-Game-Rolle fehlt. */
  scopes_without_role: Record<string, string>;
}

export interface CharacterListResponse {
  characters: CharacterInfo[];
  token_storage: string;
}

// ---------------------------------------------------------------------------
// Bestände
// ---------------------------------------------------------------------------

export interface AssetRow {
  item_id: number;
  type_id: number;
  type_name: string;
  group_name: string;
  quantity: number;
  volume: number | null;
  total_volume: number | null;
  location_id: number;
  location_type: string;
  location_flag: string;
  root_location_id: number | null;
  location_name: string;
  depth: number;
  container_name: string | null;
  is_singleton: boolean;
  is_blueprint_copy: boolean;
  fetched_at: string;
}

export interface AssetListResponse {
  rows: AssetRow[];
  total: number;
  unresolved: number;
  fetched_at: string | null;
}

export interface LocationSummary {
  location_id: number | null;
  name: string;
  location_type: string;
  items: number;
  stacks: number;
}

export interface AssetChangeRow {
  id: number;
  kind: "added" | "removed" | "quantity" | "moved";
  item_id: number;
  type_id: number;
  type_name: string;
  quantity_before: number | null;
  quantity_after: number | null;
  delta: number | null;
  location_id: number | null;
  location_name: string;
  location_before: number | null;
  observed_at: string;
}

export interface AssetChangeListResponse {
  rows: AssetChangeRow[];
  total: number;
}

export interface SyncResultResponse {
  character_id: number;
  unchanged: boolean;
  fetched: number;
  added: number;
  removed: number;
  quantity_changes: number;
  moved: number;
  named: number;
  unresolved: number;
}
