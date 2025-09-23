export type MetricPoint = {
  metric: string;
  value: number | null;
  unit?: string | null;
  updated_at?: string | null;
  stale: boolean;
  source?: string | null;
};

export type MetricsSummary = {
  coverage_ratio: MetricPoint;
  throughput_mps: MetricPoint;
  failover_latency_ms: MetricPoint;
  runbook_exit_code: MetricPoint;
  consumer_backlog_messages: MetricPoint;
};

export type RunbookExecution = {
  request_id: string;
  command: string;
  mode: string;
  window: string;
  profile: string;
  config: string | null;
  exit_code: number;
  status: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  logs: Array<Record<string, unknown>>;
  raw_output: string[];
  metadata: Record<string, unknown>;
};

export type HealthSnapshot = {
  request_id: string;
  mode: string;
  generated_at: string;
  exit_code: number;
  coverage_ratio: number | null;
  expected_total: number | null;
  active_total: number | null;
  missing_contracts: string[];
  stalled_contracts: Array<Record<string, unknown>>;
  warnings: string[];
  errors: string[];
  report: Record<string, unknown>;
};

export type StatusResponse = {
  environment_mode: string;
  active_profile: string;
  active_window: string;
  last_runbook: RunbookExecution | null;
  runbook_history: RunbookExecution[];
  health_by_request: Record<string, HealthSnapshot>;
  last_health: HealthSnapshot | null;
  last_exit_codes: Record<string, number>;
  last_updated_at: string;
};

export type TimeseriesPoint = {
  timestamp: string;
  value: number;
};

export type TimeseriesSeries = {
  metric: string;
  unit?: string | null;
  points: TimeseriesPoint[];
};

export type RunbookCommandPayload = {
  command: string;
  mode: string;
  window: string;
  profile: string;
  request_id: string;
  config?: string;
  enforce?: boolean;
  dry_run?: boolean;
  reason?: string;
};

export type RunbookExecuteResponse = {
  runbook: RunbookExecution;
  health?: HealthSnapshot | null;
};
