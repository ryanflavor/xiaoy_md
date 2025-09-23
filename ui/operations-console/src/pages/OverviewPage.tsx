import { useEffect } from "react";
import { useMetricsQuery, useRunbookMutation, useStatusQuery } from "@/hooks/useOperationsData";
import { ActionPanel, HealthStatCard, MetricChart, StatusBadge } from "@/components";
import { useTimeseriesQuery } from "@/hooks/useOperationsData";
import { useSessionStore } from "@/stores/sessionStore";
import { en } from "@/i18n/en";
import { zh } from "@/i18n/zh";

export function OverviewPage() {
  const { data: metrics } = useMetricsQuery();
  const { data: status } = useStatusQuery();
  const { setEnvironmentMode, setActiveProfile } = useSessionStore();
  const throughputSeries = useTimeseriesQuery("md_throughput_mps", 120);

  useEffect(() => {
    if (!status) {
      return;
    }
    setEnvironmentMode(status.environment_mode as "live" | "mock" | "unknown");
    setActiveProfile(status.active_profile as "primary" | "backup" | "unknown");
  }, [status, setEnvironmentMode, setActiveProfile]);

  const coverageMetric = metrics?.coverage_ratio;
  const throughputMetric = metrics?.throughput_mps;
  const failoverMetric = metrics?.failover_latency_ms;
  const backlogMetric = metrics?.consumer_backlog_messages;

  const latestHealth = status?.last_health;
  const lastRunbook = status?.last_runbook;

  return (
    <div className="flex flex-col gap-6">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <HealthStatCard
          titleEn="Coverage Ratio"
          titleZh="订阅覆盖率"
          value={formatValue(coverageMetric?.value, "99.9%")}
          unit={coverageMetric?.unit ?? "%"}
          status={determineStatus(coverageMetric?.value ?? 0.0, {
            success: 0.995,
            warning: 0.98,
          })}
          subtitle={`Updated / 更新时间: ${formatUpdated(coverageMetric?.updated_at)}`}
        />
        <HealthStatCard
          titleEn="Throughput"
          titleZh="吞吐率"
          value={formatValue(throughputMetric?.value, "-", 0)}
          unit="msg/s"
          status="info"
          subtitle={`Updated / 更新时间: ${formatUpdated(throughputMetric?.updated_at)}`}
        />
        <HealthStatCard
          titleEn="Failover Latency"
          titleZh="故障切换延迟"
          value={formatValue(failoverMetric?.value, "-", 0)}
          unit="ms"
          status={determineLatencyStatus(failoverMetric?.value ?? 0)}
          subtitle={`Updated / 更新时间: ${formatUpdated(failoverMetric?.updated_at)}`}
        />
        <HealthStatCard
          titleEn="Backlog"
          titleZh="下游堆积"
          value={formatValue(backlogMetric?.value, "-", 0)}
          unit="messages"
          status={determineStatusInverse(backlogMetric?.value ?? 0, {
            warning: 500,
            danger: 2000,
          })}
          subtitle={`Updated / 更新时间: ${formatUpdated(backlogMetric?.updated_at)}`}
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

function determineStatus(value: number, thresholds: { success: number; warning: number }) {
  if (value >= thresholds.success) {
    return "success" as const;
  }
  if (value >= thresholds.warning) {
    return "warning" as const;
  }
  return "danger" as const;
}

function determineStatusInverse(value: number, thresholds: { warning: number; danger: number }) {
  if (value >= thresholds.danger) {
    return "danger" as const;
  }
  if (value >= thresholds.warning) {
    return "warning" as const;
  }
  return "success" as const;
}

function determineLatencyStatus(value: number) {
  if (value === 0) {
    return "info" as const;
  }
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
