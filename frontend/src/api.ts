// API client + shared types (mirrors zarin/api.py responses).

export type Evidence = {
  metric_id: string; name_fa: string; definition_fa: string; formula: string;
  grain: string; caveats: string[]; sql: string; sql_kind?: "query" | "method"; params: Record<string, unknown>;
  n: number | null; period: string | null; computed_at: string;
  note_fa?: string; method_fa?: string; rule_fa?: string;
};

export type Meta = {
  range: { from: string; to: string };
  merchants: { merchant_key: string; category_title: string; sessions: number; verified: number; gmv: number; active_months: number }[];
  demo: { merchant_key: string; why: string }[];
  notes: { currency: string; fee: string; customer: string };
};

export type Overview = {
  period: { from: string; to: string };
  kpis: {
    gmv: number; verified: number; sessions: number; conv: number | null;
    median_ticket: number | null; customers: number; paid_unverified: number;
    paid_unverified_amount: number; fee_index_sum: number;
  };
  previous: { gmv: number; verified: number; sessions: number; conv: number | null } | null;
  daily: { d: string; sessions: number; verified: number; gmv: number; conv: number | null }[];
  evidence: Record<string, Evidence>;
};

export type InsightCard = {
  id: string; kind: string; card_type?: "opportunity" | "alert"; title_fa: string;
  observation_fa: string; diagnosis_fa: string; action_fa: string;
  impact_low: number; impact_mid?: number; impact_high: number; impact_label_fa: string; impact_is_count?: boolean;
  confidence: "high" | "medium" | "low"; effort: string; n: number; score: number;
  n_peers?: number; capped?: boolean; broken?: boolean;
  risk_gmv?: number; evidence: Evidence[];
};

export type Funnel = {
  stages: { id: string; label_fa: string; n: number }[];
  outcomes: Record<string, number>;
  rates: Record<string, number | null>;
  recovery: { first_fail_pool: number; recovered: number; recovery_rate: number | null; recovered_gmv: number };
  hours: { hour: number; sessions: number; verified: number }[];
  amount_bands: { band: number; lo: number; hi: number; sessions: number; conv: number }[];
  psp: { psp_code: string; attempts: number; ok_rate: number }[];
  fail_codes: { code: string; n: number }[];
  evidence: Record<string, Evidence>;
};

export type Customers = {
  low_n?: boolean;
  summary: {
    customers: number; new_customers: number; txns: number; repeat_txns: number;
    gmv: number; repeat_gmv: number; repeat_customers: number;
  };
  concentration: { top5_share: number | null; n: number };
  interval: { median_days: number | null; n: number };
  cohorts: { first_month: string; k: number; active: number; cohort_size: number }[];
  dormant: { n: number; gmv: number };
  evidence: Record<string, Evidence>;
};

export type Peers = {
  group: { n: number; rule_fa: string; level: string; sufficient: boolean; me: Record<string, unknown> };
  rows: {
    metric: string; value: number | null; suppressed: boolean;
    p25?: number; p50?: number; p75?: number; percentile?: number; n_peers?: number;
    higher_better?: boolean; low_n?: boolean;
  }[];
  evidence: Evidence;
};

export type Changes = {
  before: { from: string; to: string; sessions: number; conv: number; ticket: number; gmv: number };
  after: { from: string; to: string; sessions: number; conv: number; ticket: number; gmv: number };
  delta_gmv: number; decomposable: boolean;
  contrib: { sessions?: number; conv?: number; ticket?: number };
  conv_drivers: Record<string, number>;
  evidence: Evidence;
};

export type CopilotAnswer = {
  answer_fa: string; intent: string; evidence: Evidence[]; note_fa: string;
  confidence?: "high" | "medium" | "low";
  source?: "deterministic" | "llm"; grounded?: boolean; fallback?: boolean;
  quality_flags?: string[]; provider?: string | null; model?: string | null;
  latency_ms?: number | null; total_tokens?: number | null; cost_usd?: number | null;
};

// --- Control Center ----------------------------------------------------------
export type AdminPlatform = {
  period: { from: string; to: string };
  kpis: {
    total_merchants: number; active_merchants: number; sessions: number; verified: number;
    gmv: number; conv: number | null; no_attempt_rate: number | null;
    paid_unverified: number; paid_unverified_amount: number; recovered: number; recovered_gmv: number;
  };
  categories: { category: string; merchants: number; sessions: number; gmv: number | null }[];
  concentration: { top5_share: number | null; n_merchants: number };
  anomalies: { reversed_sessions: number; verified_wo_ok_try: number };
  insights: { severity: string; title_fa: string; body_fa: string; action_fa: string }[];
};

export type AdminPerformance = {
  total: number; has_data: boolean; note_fa?: string;
  error_rate?: number; client_error_rate?: number; throughput_rps?: number;
  latency_ms?: { p50: number | null; p95: number | null; p99: number | null };
  endpoints?: { path: string; count: number; error_rate: number; p50: number | null; p95: number | null; p99: number | null }[];
  attention?: { severity?: string; path?: string; fa: string }[];
};

export type AdminAI = {
  total: number; has_data: boolean; note_fa?: string;
  llm_requests?: number; deterministic_requests?: number; success?: number; failed?: number;
  fallback?: number; fallback_rate?: number; grounded_rate?: number; evidence_coverage?: number;
  zero_evidence?: number; hallucination_risk?: number;
  latency_ms?: { p50: number | null; p95: number | null; p99: number | null };
  tokens_total?: number; cost_usd_total?: number; cost_per_request?: number;
  models?: { model: string; count: number }[]; providers?: { provider: string; count: number }[];
  intents?: { intent: string; count: number }[];
  feedback?: { total: number; useful: number; not_useful: number };
  recent?: { ts: string; surface: string; intent: string; source: string; fallback: boolean;
             grounded: boolean; model: string | null; latency_ms: number | null;
             cost_usd: number | null; evidence_count: number }[];
};

export type AdminSources = {
  sources: {
    id: string; name_fa: string; kind: string; configured: boolean; connected: boolean;
    status: string; is_truth: boolean; freshness: string | null; note_fa: string; error: string | null;
  }[];
  cross_source_insights: { id: string; title_fa: string; observation_fa: string; action_fa: string; caveat_fa: string }[];
  cross_source_note_fa: string | null;
};

export type AdminEval = {
  merchant: string; period: { from: string; to: string }; total: number; passed: number;
  indicators: {
    deterministic_correctness: number; grounding_quality: number;
    refusal_safety: number | null; language_quality: null; business_usefulness: null;
  };
  cases: { id: string; dimension: string; intent: string; expected_intent: string;
           confidence: string | null; evidence_count: number; passed: boolean }[];
  note_fa: string;
};

export type Quality = {
  outcomes: { outcome: string; n: number; amount: number | null }[];
  concentration: { top5: number; n: number };
  anomalies: { verified_wo_ok_try: number; reversed_sessions: number };
  rules_fa: string[];
};

export type SessionSample = {
  rows: { session_key: number; d: string; amount: number; outcome: string; n_tries: number;
          first_try_status: string | null; last_try_status: string | null; win_psp: string | null }[];
  total: number; note_fa: string;
};

export async function get<T>(path: string, params: Record<string, string | undefined>,
                             method: "GET" | "POST" = "GET"): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== "") qs.set(k, v);
  const res = await fetch(`/api/${path}?${qs}`, { method });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}
