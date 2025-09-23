import { expect, test } from "@playwright/test";

const metricsPayload = {
  coverage_ratio: {
    metric: "md_subscription_coverage_ratio",
    value: 0.999,
    unit: "%",
    updated_at: "2025-09-22T08:00:00+08:00",
    stale: false,
    source: "health_report",
  },
  throughput_mps: {
    metric: "md_throughput_mps",
    value: 5100,
    unit: "msg/s",
    updated_at: "2025-09-22T08:00:05+08:00",
    stale: false,
    source: "prometheus",
  },
  failover_latency_ms: {
    metric: "md_failover_latency_ms",
    value: 1800,
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
    value: 20,
    unit: "messages",
    updated_at: "2025-09-22T08:00:05+08:00",
    stale: false,
    source: "prometheus",
  },
};

const statusPayload = {
  environment_mode: "live",
  active_profile: "primary",
  active_window: "day",
  last_runbook: null,
  runbook_history: [],
  health_by_request: {},
  last_health: null,
  last_exit_codes: {},
  last_updated_at: "2025-09-22T08:00:10+08:00",
};

const seriesPayload = {
  metric: "md_throughput_mps",
  unit: "msg/s",
  points: [
    { timestamp: "2025-09-22T07:55:00+08:00", value: 4800 },
    { timestamp: "2025-09-22T07:56:00+08:00", value: 5000 },
    { timestamp: "2025-09-22T07:57:00+08:00", value: 5100 },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript((env) => {
    window.__OPS_ENV__ = env;
  }, {
    VITE_OPS_API_BASE_URL: "/api",
    VITE_OPS_API_TOKEN: "",
  });

  await page.route("**/ops/metrics/summary", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(metricsPayload),
    });
  });
  await page.route("**/ops/status", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(statusPayload),
    });
  });
  await page.route("**/ops/metrics/timeseries?*", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(seriesPayload),
    });
  });
  await page.route("**/ops/runbooks/execute", async (route) => {
    const request = route.request();
    let body = {};
    try {
      body = request.postDataJSON();
    } catch (error) {
      body = {};
    }
    const command = body?.command ?? "start";

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        runbook: {
          request_id: "mock",
          command,
          mode: body?.mode ?? "mock",
          window: body?.window ?? "day",
          profile: body?.profile ?? "live",
          config: body?.config ?? "primary",
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
      }),
    });
  });
});

test("overview renders metrics from mock API", async ({ page }) => {
  await page.goto("/");

  const coverageCard = page.locator("article", {
    hasText: /Coverage Ratio/,
  });
  await expect(coverageCard).toBeVisible();
  await expect(coverageCard).toContainText(/Coverage Ratio/);
  await expect(coverageCard).not.toContainText("--");

  const throughputCard = page.locator("article", {
    hasText: /Throughput/,
  });
  await expect(throughputCard).toBeVisible();

  const failoverButton = page.getByRole("button", {
    name: /Trigger Failover/,
  });
  await failoverButton.click();

  const confirmDialog = page.locator("dialog[open]");
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole("button", { name: /Execute/ }).click();

  await expect(page.getByText(/Runbook failover completed/)).toBeVisible();
});
