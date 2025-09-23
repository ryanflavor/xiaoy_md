import { getJson, postJson } from "./apiClient";
import type {
  MetricsSummary,
  RunbookCommandPayload,
  RunbookExecuteResponse,
  StatusResponse,
  TimeseriesSeries,
} from "./types";

export function fetchMetricsSummary() {
  return getJson<MetricsSummary>("/ops/metrics/summary");
}

export function fetchStatus() {
  return getJson<StatusResponse>("/ops/status");
}

export function fetchTimeseries(metric: string, minutes = 60) {
  const params = new URLSearchParams({ metric, minutes: String(minutes) });
  return getJson<TimeseriesSeries>(`/ops/metrics/timeseries?${params.toString()}`);
}

export function executeRunbook(payload: RunbookCommandPayload) {
  return postJson<RunbookExecuteResponse, RunbookCommandPayload>(
    "/ops/runbooks/execute",
    payload
  );
}
