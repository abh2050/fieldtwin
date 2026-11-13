// Shapes returned by the FieldTwin API (apps/api). Only fields the screens use are listed.

export type Health = {
  status: "ok" | "degraded";
  checks: { database: string; role?: string; latest_migration?: string; writes_enabled?: boolean };
  disclosure: string;
};
export type Me = { actor_id: string; role: "VIEWER" | "OPERATOR" | "MAINTENANCE_SUPERVISOR" };

export type Asset = {
  asset_id: string;
  facility_id: string;
  parent_asset_id: string | null;
  asset_type: string;
  asset_name: string;
  equipment_class_id: string | null;
  operating_status: string | null;
  is_fictional: boolean;
  provenance_class: string;
  transformation_id: string | null;
};
export type AssetDetail = Asset & {
  children: string[];
  sensors: { tag_id: string; native_tag_name: string; canonical_metric: string; physical_quantity: string; unit_id: string; pressure_reference_type: string; sampling_frequency: string }[];
  network_nodes: { node_id: string; node_type: string; local_x_m: number; local_y_m: number }[];
  work_orders: { external_id: string; status: string; priority_band: string | null; created_at: string }[];
};

export type NetworkNode = { node_id: string; node_type: string; asset_id: string | null; local_x_m: number; local_y_m: number; asset_type: string | null; parent_asset_id: string | null };
export type NetworkEdge = { edge_id: string; edge_type: string; from_node_id: string; to_node_id: string; element_asset_id: string | null; length_m: number | null; diameter_m: number | null };

export type Run = {
  scenario_run_id: string;
  scenario_id: string;
  case_name: string;
  target_asset_id: string | null;
  affected_asset_id: string | null;
  simulator_name: string;
  simulator_version: number;
  config_sha256: string;
  output_sha256: string;
  output_uri: string;
  random_seed: number;
  sample_count: number;
  sampling_interval_s: number;
  fault_onset_offset_s: number | null;
};
export type Replay = { scenario_run_id: string; state: "PLAYING" | "PAUSED" | "STOPPED" | "FINISHED"; position_s: number; duration_s: number; speed: number; updated_by: string };
export type Scenario = { scenario_id: string; scenario_name: string; scenario_description: string; scenario_version: number; random_seed: number; runs: Run[]; alarm_count: number; replay: Replay | null };

export type Alarm = { alarm_id: string; scenario_id: string; scenario_run_id: string; started_at: string; first_alarm_at: string; score: number; threshold: number; model_id: string; model_version: string; recommendation_id: string | null; action: string | null; priority_band: string | null; provenance_class: string };

export type Term = { name: string; points: number; input: string; rule: string };
export type Recommendation = {
  recommendation_id: string;
  alarm_id: string;
  scenario_id: string;
  scenario_run_id: string;
  decided_at: string;
  action: string;
  candidate_assets: string[];
  suppressed_assets: string[];
  priority_score: number;
  priority_band: string | null;
  respond_within_h: number | null;
  terms: Term[];
  explanation: string[];
  rules_version: number;
  provenance_class: string;
  work_order_id: string | null;
  work_order_status: string | null;
};

export type Transition = { sequence: number; decision: string; from_status: string | null; to_status: string; actor_id: string; actor_kind: string; actor_role: string; justification: string; decided_at: string; recorded_at: string };
export type WorkOrder = { work_order_id: string; scenario_id: string; asset_id: string; recommended_action: string; priority: number; priority_band: string | null; status: string; created_at: string; recommendation_id: string; transitions: Transition[]; decided_by_kinds: string[] };

export type Source = { path: string; sha256: string };
export type Stats = { mean: number; p5: number; p50: number; p95: number };
