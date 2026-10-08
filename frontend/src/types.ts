export interface Diff { path: string; before: unknown; after: unknown }
export interface Candidate {
  execution_compatible?: boolean;
  compatibility_note?: string;
  manifest_hash: string; request: string; diff: Diff[]; confirmed: boolean;
  validation: { passed?: boolean; errors?: string[]; layers?: Record<string, { passed?: boolean; errors?: string[]; status?: string }> };
}
export interface Status { model: { enabled: boolean; remaining_calls: number; reason: string; actions?: string[] }; profile: string;
  coding?: { enabled: boolean; remaining_calls: number; reason: string; modes: string[];
    tasks?: { operation_id: string; request: string; mode: 'single' | 'auto' }[] };
}
export interface CodingRun {
  operation_id: string; request: string; mode: 'single' | 'auto';
  status: 'running' | 'completed' | 'interrupted' | 'failed'; stage: string; error: string | null;
  manifest_hash: string | null; summary: string; review_text: string;
  spawned_thread_ids: string[]; spawn_attempts: number; seconds: number | null;
  budget: { reserved: number; completed: number; failed: number; unknown: number; known_cost_usd: string;
    unknown_cost_reserved_usd: string; max_calls: number; cost_cap_usd: string } | null;
}
export interface RequestSummary {
  request_id: string; manifest_hash: string; goal: string; status: string;
  charged_battles: number; max_battles: number; verdict?: string | null;
}
export interface Battle { outcome: string; elapsed_av?: string; trace_sha256?: string }
export interface Row { policy: string; seed: number; baseline: Battle; candidate: Battle }
export interface Report {
  verdict: string; structural_verdict?: string; summary?: string; agent_decision_note?: string;
  errors?: string[]; limitations?: string[]; observations?: { tool?: string; [key: string]: unknown }[];
  stop_reason?: string; jobs?: { job_id: string; result: { rows?: Row[]; structural_verdict?: string }; [key: string]: unknown }[];
  [key: string]: unknown;
}
export interface Facts {
  verdict: string; distinct_pairs: number;
  comparisons: { policy: string; seed: number; baseline_av: string; candidate_av: string; delta_av: string; direction: string }[];
  transitions: Record<string, number>; original_error_count: number;
  basis: string; meaning: string; limit: string; model_text_status: string;
}
export interface RequestDetail { request: RequestSummary & { report: Report | null }; facts: Facts | null; report_text: string | null }
export interface Operation {
  operation_id: string; kind: 'draft' | 'verify' | 'coding'; status: 'running' | 'completed' | 'interrupted' | 'failed';
  result: { status?: string; message?: string; proposal_message?: string; candidate?: Candidate; [key: string]: unknown } | null;
  error: string | null;
}
export interface Trace {
  excerpt: string;
  selection?: { selected_events?: number; total_events?: number; limit?: string; [key: string]: unknown };
  reference?: { variant?: string; seed?: number; policy?: string; [key: string]: unknown };
  [key: string]: unknown;
}

export interface TaskRecord {
 task_id: string; kind: string; request: string; status: string; origin: string;
 candidate_id: string | null; candidate: Candidate | null; applied: boolean;
 report: RequestDetail | null; author_result?: { message?: string; proposal_message?: string } | null;
 events: { kind: string; time: string; detail: Record<string, unknown> }[];
}
