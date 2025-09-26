import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import {
  executeRunbook,
  fetchMetricsSummary,
  fetchStatus,
  fetchTimeseries,
} from "@/services/opsConsole";
import type {
  MetricsSummary,
  RunbookCommandPayload,
  RunbookExecuteResponse,
  StatusResponse,
  TimeseriesSeries,
} from "@/services/types";

const STATUS_QUERY_KEY = ["ops", "status"];
const METRICS_QUERY_KEY = ["ops", "metrics"];

export function useStatusQuery() {
  return useQuery<StatusResponse>({
    queryKey: STATUS_QUERY_KEY,
    queryFn: fetchStatus,
    refetchInterval: 10000,
  });
}

export function useMetricsQuery() {
  return useQuery<MetricsSummary>({
    queryKey: METRICS_QUERY_KEY,
    queryFn: fetchMetricsSummary,
    refetchInterval: 60000,
  });
}

export function useTimeseriesQuery(metric: string, minutes = 60) {
  return useQuery<TimeseriesSeries>({
    queryKey: ["ops", "series", metric, minutes],
    queryFn: () => fetchTimeseries(metric, minutes),
    refetchInterval: 30000,
  });
}

export function useRunbookMutation() {
  const client = useQueryClient();
  return useMutation<RunbookExecuteResponse, Error, Partial<RunbookCommandPayload>>({
    mutationFn: async (partial) => {
      const payload: RunbookCommandPayload = {
        command: partial.command ?? "start",
        mode: partial.mode ?? "live",
        window: partial.window ?? "day",
        profile: partial.profile ?? "live",
        request_id: partial.request_id ?? nanoid(),
        config: partial.config,
        enforce: partial.enforce,
        dry_run: partial.dry_run,
        reason: partial.reason,
      };
      return executeRunbook(payload);
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: STATUS_QUERY_KEY });
      void client.invalidateQueries({ queryKey: METRICS_QUERY_KEY });
      void client.invalidateQueries({ queryKey: ["ops", "series"] });
    },
  });
}
