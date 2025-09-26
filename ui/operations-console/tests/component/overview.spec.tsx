/// <reference types="vitest" />

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OverviewPage } from "@/pages/OverviewPage";
import type { MetricsSummary, RunbookExecuteResponse, StatusResponse, TimeseriesSeries } from "@/services/types";
import { useSessionStore } from "@/stores/sessionStore";

const metricsPayload: MetricsSummary = {
  coverage_ratio: {
    metric: "md_subscription_coverage_ratio",
    value: 0.9987,
    unit: "%",
    updated_at: "2025-09-22T08:00:00+08:00",
    stale: false,
    source: "health_report",
    context: {
      expected_total: 1280,
      active_total: 1278,
      matched_total: 1278,
      ignored_total: 2,
      ignored_symbols: ["OPT1", "OPT2"],
    },
  },
  throughput_mps: {
    metric: "md_throughput_mps",
    value: 5200,
    unit: "msg/s",
    updated_at: "2025-09-22T08:00:05+08:00",
    stale: false,
    source: "prometheus",
  },
  failover_latency_ms: {
    metric: "md_failover_latency_ms",
    value: 1600,
    unit: "ms",
    updated_at: "2025-09-22T08:00:05+08:00",
    stale: false,
    source: "prometheus",
  },
  runbook_exit_code: {
    metric: "md_runbook_exit_code",
    value: 0,
    unit: null,
    updated_at: "2025-09-22T08:00:07+08:00",
    stale: false,
    source: "prometheus",
  },
  consumer_backlog_messages: {
    metric: "consumer_backlog_messages",
    value: 12,
    unit: "messages",
    updated_at: "2025-09-22T08:00:05+08:00",
    stale: false,
    source: "prometheus",
  },
};

const statusPayload: StatusResponse = {
  environment_mode: "live",
  active_profile: "primary",
  active_window: "day",
  last_runbook: null,
  runbook_history: [],
  health_by_request: {},
  last_health: {
    request_id: "hc-1",
    mode: "mock",
    generated_at: "2025-09-22T07:59:59+08:00",
    exit_code: 0,
    coverage_ratio: 0.999,
    expected_total: 1280,
    active_total: 1280,
    matched_total: 1280,
    ignored_total: 0,
    ignored_symbols: [],
    missing_contracts: [],
    stalled_contracts: [],
    warnings: [],
    errors: [],
    report: {},
  },
  last_exit_codes: {
    health_check: 0,
  },
  last_updated_at: "2025-09-22T08:00:10+08:00",
};

const seriesPayload: TimeseriesSeries = {
  metric: "md_throughput_mps",
  unit: "msg/s",
  points: [
    { timestamp: "2025-09-22T07:55:00+08:00", value: 4800 },
    { timestamp: "2025-09-22T07:56:00+08:00", value: 5100 },
    { timestamp: "2025-09-22T07:57:00+08:00", value: 5200 },
  ],
};

describe("OverviewPage", () => {
  let originalFetch: typeof global.fetch;
  let metricsResponse: MetricsSummary;
  let statusResponse: StatusResponse;
  let seriesResponse: TimeseriesSeries;

  beforeEach(() => {
    metricsResponse = clone(metricsPayload);
    statusResponse = clone(statusPayload);
    seriesResponse = clone(seriesPayload);
    originalFetch = global.fetch;
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/ops/metrics/summary")) {
        return mockResponse(metricsResponse);
      }
      if (url.includes("/ops/status")) {
        return mockResponse(statusResponse);
      }
      if (url.includes("/ops/metrics/timeseries")) {
        return mockResponse(seriesResponse);
      }
      if (url.includes("/ops/runbooks/execute")) {
        const body: RunbookExecuteResponse = {
          runbook: {
            request_id: "test",
            command: "start",
            mode: "mock",
            window: "day",
            profile: "live",
            config: "primary",
            exit_code: 0,
            status: "success",
            started_at: new Date().toISOString(),
            finished_at: new Date().toISOString(),
            duration_ms: 0,
            logs: [],
            raw_output: [],
            metadata: {},
          },
          health: null,
        };
        return mockResponse(body);
      }
      throw new Error(`Unhandled fetch for ${url}`);
    }) as typeof global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.clearAllMocks();
  });

  it("renders live metrics and updates session store", async () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      screen.getByText(/Coverage\b/);
    });
    await waitFor(() => {
      screen.getByText(/Subscribed: 1278\/1280/);
    });
    screen.getByText(/Coverage: 99\.87%/);
    expect(screen.getAllByText(/Throughput/).length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(useSessionStore.getState().environmentMode).toBe("live")
    );
    await waitFor(() =>
      expect(useSessionStore.getState().activeProfile).toBe("primary")
    );
  });

  it("shows stale coverage data with last known snapshot", async () => {
    metricsResponse.coverage_ratio = {
      metric: "md_subscription_coverage_ratio",
      value: 0.905379,
      unit: null,
      updated_at: "2025-09-25T23:49:20+08:00",
      stale: true,
      source: "health_report",
    };
    statusResponse.last_health = {
      request_id: "hc-stale",
      mode: "live",
      generated_at: "2025-09-25T23:49:20+08:00",
      exit_code: 2,
      coverage_ratio: 0.905379,
      expected_total: 19520,
      active_total: 17673,
      matched_total: 17673,
      ignored_total: 12,
      ignored_symbols: ["TEST-1", "TEST-2"],
      missing_contracts: ["M1", "M2", "M3", "M4"],
      stalled_contracts: [],
      warnings: [],
      errors: ["Coverage ratio below threshold", "Missing contracts"],
      report: {},
    };

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      screen.getByText(/Coverage: 90\.54%/);
    });
    screen.getByText(/Stale /);
    screen.getByText(/Missing: 4/);
    expect(screen.getAllByText(/Exit 2/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^--$/)).toBeNull();
  });
});

function mockResponse<T>(body: T): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function clone<T>(data: T): T {
  return JSON.parse(JSON.stringify(data)) as T;
}
