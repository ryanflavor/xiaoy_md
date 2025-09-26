import { useEffect } from "react";
import { useMetricsQuery, useRunbookMutation, useStatusQuery } from "@/hooks/useOperationsData";
import {
  ActionPanel,
  ErrorBanner,
  HealthStatCard,
  MetricChart,
  StatusBadge,
} from "@/components";
import { useTimeseriesQuery } from "@/hooks/useOperationsData";
import type { MetricPoint } from "@/services/types";
import { useSessionStore } from "@/stores/sessionStore";
import { en } from "@/i18n/en";
import { zh } from "@/i18n/zh";

export function OverviewPage() {
  const statusQuery = useStatusQuery();
  const metricsQuery = useMetricsQuery();
  const throughputSeries = useTimeseriesQuery("md_throughput_mps", 120);
  const status = statusQuery.data;
  const metrics = metricsQuery.data;
  const latestHealth = status?.last_health;
  const lastRunbook = status?.last_runbook;
  const { setEnvironmentMode, setActiveProfile } = useSessionStore();

  const firstError =
    statusQuery.isError || metricsQuery.isError || throughputSeries.isError
      ? statusQuery.error || metricsQuery.error || throughputSeries.error
      : null;

  useEffect(() => {
    if (!status) {
      return;
    }
    setEnvironmentMode(status.environment_mode as "live" | "mock" | "unknown");
    setActiveProfile(status.active_profile as "primary" | "backup" | "unknown");
  }, [status, setEnvironmentMode, setActiveProfile]);

  const coverageMetric = metrics?.coverage_ratio;
  const coverageValue = coverageMetric?.value ?? null;
  const coverageStatus = determineStatus(coverageValue, {
    success: 0.995,
    warning: 0.98,
  });
  const coverageContext = (coverageMetric?.context ?? {}) as Record<string, unknown>;
  const expectedTotal =
    coerceNumber(coverageContext.expected_total) ??
    coerceNumber(latestHealth?.expected_total);
  const activeTotal =
    coerceNumber(coverageContext.active_total) ??
    coerceNumber(latestHealth?.active_total);
  const matchedTotal =
    coerceNumber(coverageContext.matched_total) ??
    coerceNumber(latestHealth?.matched_total);
  const ignoredTotal =
    coerceNumber(coverageContext.ignored_total) ??
    coerceNumber(latestHealth?.ignored_total);
  const ignoredSymbolsRaw =
    coverageContext.ignored_symbols ?? latestHealth?.ignored_symbols ?? [];
  const ignoredSymbols = Array.isArray(ignoredSymbolsRaw)
    ? (ignoredSymbolsRaw as string[])
    : [];
  const coverageUpdatedAt = coverageMetric?.updated_at ?? latestHealth?.generated_at ?? null;
  const coverageStale = coverageMetric?.stale ?? false;
  const missingContracts = latestHealth?.missing_contracts ?? [];
  const missingCount = missingContracts.length;
  const missingPreview = missingContracts.slice(0, 3);
  const missingPreviewText = missingPreview.join(", ");
  const healthErrors = latestHealth?.errors ?? [];
  const coverageDisplay =
    matchedTotal
    ?? activeTotal
    ?? (coverageValue !== null && expectedTotal !== null
        ? Math.round(coverageValue * expectedTotal)
        : null);
  const coverageTrend =
    coverageValue !== null
      ? `Coverage: ${(coverageValue * 100).toFixed(2)}%${coverageStale ? " • Stale / 数据陈旧" : ""}`
      : undefined;
  const coverageSubtitle = buildCoverageSubtitle(
    coverageUpdatedAt,
    expectedTotal,
    coverageDisplay,
    ignoredTotal,
    coverageStale,
    missingCount,
    latestHealth?.exit_code ?? null,
  );
  const coverageTooltipLines = [
    coverageValue !== null
      ? `Coverage ${(coverageValue * 100).toFixed(2)}%`
      : null,
    coverageStale
      ? `Data stale: ${formatStaleAge(coverageUpdatedAt) ?? "unknown"}`
      : null,
    coverageDisplay !== null && expectedTotal !== null
      ? `Subscribed ${coverageDisplay}/${expectedTotal}`
      : null,
    missingCount > 0
      ? `Missing ${missingCount} contracts${missingPreviewText ? ` (e.g. ${missingPreviewText}${missingCount > missingPreview.length ? "…" : ""})` : ""}`
      : null,
    ignoredSymbols.length
      ? `Ignored: ${ignoredSymbols.slice(0, 5).join(", ")}${ignoredSymbols.length > 5 ? "…" : ""}`
      : null,
    healthErrors.length
      ? `Errors: ${healthErrors.slice(0, 2).join("; ")}${healthErrors.length > 2 ? "…" : ""}`
      : null,
  ].filter(Boolean) as string[];

  const throughputMetric = metrics?.throughput_mps;
  const failoverMetric = metrics?.failover_latency_ms;
  const backlogMetric = metrics?.consumer_backlog_messages;

  return (
    <div className="flex flex-col gap-6">
      {firstError ? <ErrorBanner error={firstError} /> : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <HealthStatCard
          titleEn="Coverage"
          titleZh="订阅覆盖"
          value={formatValue(coverageDisplay, "--", 0)}
          unit="contracts"
          status={coverageStatus}
          trend={coverageTrend}
          subtitle={coverageSubtitle}
          tooltip={coverageTooltipLines.length ? coverageTooltipLines.join("\n") : undefined}
        />
        <HealthStatCard
          titleEn="Throughput"
          titleZh="吞吐率"
          value={formatValue(throughputMetric?.value, "-", 0)}
          unit="msg/s"
          status="info"
          subtitle={buildMetricSubtitle(
            throughputMetric,
            "Awaiting metrics / 等待采样"
          )}
        />
        <HealthStatCard
          titleEn="Failover Latency"
          titleZh="故障切换延迟"
          value={formatValue(failoverMetric?.value, "-", 0)}
          unit="ms"
          status={determineLatencyStatus(failoverMetric)}
          subtitle={buildMetricSubtitle(
            failoverMetric,
            "No recent failover / 暂无近期切换"
          )}
        />
        <HealthStatCard
          titleEn="Backlog"
          titleZh="下游堆积"
          value={formatValue(backlogMetric?.value, "-", 0)}
          unit="messages"
          status={determineStatusInverse(backlogMetric?.value, {
            warning: 500,
            danger: 2000,
          })}
          subtitle={buildMetricSubtitle(
            backlogMetric,
            "No exporter data / 暂无下游指标"
          )}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[2fr,1fr]">
        <MetricChart
          titleEn="Throughput Trend"
          titleZh="吞吐趋势"
          unit="msg/s"
          points={throughputSeries.data?.points ?? []}
        />
        <div className="card-surface flex h-72 flex-col gap-4">
          <header>
            <h3 className="text-lg font-semibold text-neutral-100">
              {en.sections.actions}
              <span className="ml-2 text-sm text-neutral-500">{zh.sections.actions}</span>
            </h3>
          </header>
          <div className="flex flex-col gap-3 text-sm text-neutral-300">
            <div className="flex items-center gap-3">
              <StatusBadge
                status="info"
                labelEn={latestHealth ? `Health Exit ${latestHealth.exit_code}` : "Pending"}
                labelZh={latestHealth ? `健康检查返回 ${latestHealth.exit_code}` : "待执行"}
              />
              {lastRunbook ? (
                <span className="text-xs text-neutral-400">
                  Last Runbook / 最近 Runbook: {lastRunbook.command} @
                  {" "}
                  {formatUpdated(lastRunbook.finished_at)}
                </span>
              ) : null}
            </div>
            <p>
              Execute runbook actions with confirmation for high-safety operations. 所有操作需确认，确保安全可控。
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <ActionPanel
          titleEn="Failover to Backup"
          titleZh="切换至备份账户"
          descriptionEn="Switch active feed to backup credentials with automated verifications."
          descriptionZh="自动执行切换并校验备份账户及健康。"
          actionLabelEn="Trigger Failover"
          actionLabelZh="触发故障切换"
          payload={{
            command: "failover",
            mode: "live",
            window: useSessionStore.getState().sessionWindow,
            profile: "live",
            config: "backup",
            reason: "Manual failover from console",
          }}
          confirmationMessage="Confirm failover to backup feed? / 确认切换到备份行情源？"
          dryRunPreview="Dry-run executes health check and permission validation before switching. / 演练模式会先执行健康检查与权限校验。"
        />
        <ActionPanel
          titleEn="Failback to Primary"
          titleZh="回切至主账户"
          descriptionEn="Return to the primary account once backup stability is verified."
          descriptionZh="备份稳定后自动回切主账户并记录指标。"
          actionLabelEn="Trigger Failback"
          actionLabelZh="触发回切"
          payload={{
            command: "failback",
            mode: "live",
            window: useSessionStore.getState().sessionWindow,
            profile: "live",
            config: "primary",
            reason: "Manual failback from console",
          }}
          confirmationMessage="Confirm failback to primary feed? / 确认回切到主行情源？"
        />
      </section>
    </div>
  );
}

function formatValue(value: number | null | undefined, fallback: string, fractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return fallback;
  }
  if (fractionDigits === 0) {
    return Math.round(value).toString();
  }
  return value.toFixed(fractionDigits);
}

function coerceNumber(value: unknown): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildCoverageSubtitle(
  updatedAt: string | null | undefined,
  expected: number | null,
  covered: number | null,
  ignored: number | null,
  stale: boolean,
  missingCount: number,
  exitCode: number | null,
) {
  const parts: string[] = [];
  if (updatedAt) {
    const base = `Last health / 最近检查: ${formatUpdated(updatedAt)}`;
    const ageLabel = formatStaleAge(updatedAt);
    parts.push(
      stale
        ? `${base}${ageLabel ? ` (${ageLabel})` : ""}`
        : `Updated / 更新时间: ${formatUpdated(updatedAt)}`,
    );
  } else if (stale) {
    parts.push("Data stale / 数据陈旧");
  }

  if (expected !== null && covered !== null) {
    parts.push(`Subscribed: ${covered}/${expected}`);
  }
  if (missingCount > 0) {
    parts.push(`Missing: ${missingCount}`);
  }
  if (ignored && ignored > 0) {
    parts.push(`Ignored: ${ignored}`);
  }
  if (typeof exitCode === "number") {
    parts.push(`Exit ${exitCode}`);
  }

  if (parts.length === 0) {
    return "Awaiting health check / 等待健康检查";
  }
  return parts.join(" • ");
}

function buildMetricSubtitle(metric: MetricPoint | undefined, emptyFallback: string) {
  if (!metric || metric.value === null || metric.value === undefined || metric.stale) {
    return emptyFallback;
  }
  return `Updated / 更新时间: ${formatUpdated(metric.updated_at ?? null)}`;
}

function determineStatus(
  value: number | null | undefined,
  thresholds: { success: number; warning: number },
) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "info" as const;
  }
  if (value >= thresholds.success) {
    return "success" as const;
  }
  if (value >= thresholds.warning) {
    return "warning" as const;
  }
  return "danger" as const;
}

function determineStatusInverse(
  value: number | null | undefined,
  thresholds: { warning: number; danger: number },
) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "info" as const;
  }
  if (value >= thresholds.danger) {
    return "danger" as const;
  }
  if (value >= thresholds.warning) {
    return "warning" as const;
  }
  return "success" as const;
}

function determineLatencyStatus(metric: MetricPoint | undefined) {
  if (!metric || metric.value === null || metric.value === undefined || metric.stale) {
    return "info" as const;
  }
  const value = metric.value;
  if (value <= 2000) {
    return "success" as const;
  }
  if (value <= 5000) {
    return "warning" as const;
  }
  return "danger" as const;
}

function formatUpdated(updatedAt: string | null | undefined) {
  if (!updatedAt) {
    return "--";
  }
  return new Date(updatedAt).toLocaleString("zh-CN", {
    hour12: false,
  });
}

function formatStaleAge(updatedAt: string | null | undefined): string | null {
  if (!updatedAt) {
    return null;
  }
  const timestamp = Date.parse(updatedAt);
  if (Number.isNaN(timestamp)) {
    return null;
  }
  const diffMs = Date.now() - timestamp;
  if (!Number.isFinite(diffMs) || diffMs < 0) {
    return null;
  }

  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diffMs < minute) {
    return "moments ago / 刚刚";
  }
  if (diffMs < hour) {
    const minutes = Math.floor(diffMs / minute);
    return `${minutes}m ago / ${minutes} 分钟前`;
  }
  if (diffMs < day) {
    const hours = Math.floor(diffMs / hour);
    return `${hours}h ago / ${hours} 小时前`;
  }
  const days = Math.floor(diffMs / day);
  return `${days}d ago / ${days} 天前`;
}
