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

export type AIProvenance = {
  mode: string; model: string; fallback: boolean; grounded: boolean;
  latency_ms: number; cost_usd: number; error?: string | null;
};

export type CopilotAnswer = {
  answer_fa: string; intent: string; evidence: Evidence[]; note_fa: string; ai?: AIProvenance;
};

export type AdminCopilotAnswer = { answer_fa: string; intent: string; ai: AIProvenance };

export type Quality = {
  outcomes: { outcome: string; n: number; amount: number | null }[];
  concentration: { top5: number; n: number };
  anomalies: { verified_wo_ok_try: number; reversed_sessions: number };
  rules_fa: string[];
};

export type SourceStatus = {
  id: string; label: string; configured: boolean; state: string; detail: string; last_sync?: string | null;
};

export type SourceInsight = {
  id: string; source: string; title_fa: string; observation_fa: string; action_fa: string;
  metric: string; current: number; previous: number | null; change: number | null; sample_days: number; caveat_fa: string;
};

export type AdminOps = {
  period: { from: string; to: string };
  platform: { sessions: number; verified: number; gmv: number; merchants: number; avg_tries: number };
  data_quality: { paid_unverified: number; no_attempt: number; reversed: number };
  api: {
    requests: number; success_rate: number | null; error_rate: number | null;
    avg_latency_ms: number | null; p95_latency_ms: number | null; routes: Record<string, number>;
  };
  ai: {
    requests: number; success_rate: number | null; grounded_rate: number | null; fallback_rate: number | null;
    avg_latency_ms: number | null; p95_latency_ms: number | null; cost_usd: number;
    models: Record<string, number>; intents: Record<string, number>; openrouter_configured: boolean; default_model: string;
    recent: { ts: string; merchant: string; intent: string; mode: string; model: string; latency_ms: number; success: boolean; fallback: boolean; grounded: boolean; evidence_count: number; cost_usd: number }[];
  };
  sources: SourceStatus[];
  source_insights: SourceInsight[];
  ga4: null | { period: { from: string; to: string }; synced_at: string; totals: { sessions: number; users: number; events: number; purchase_revenue: number } };
  slo: { target_api_p95_ms: number; target_ai_grounded_rate: number; target_ai_fallback_rate: number; target_success_rate: number };
};

export type SessionSample = {
  rows: { session_key: number; d: string; amount: number; outcome: string; n_tries: number;
          first_try_status: string | null; last_try_status: string | null; win_psp: string | null }[];
  total: number; note_fa: string;
};

export async function get<T>(path: string, params: Record<string, string | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== "") qs.set(k, v);
  const res = await fetch(`/api/${path}?${qs}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}
