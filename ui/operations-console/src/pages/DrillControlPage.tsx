import { ActionPanel, ErrorBanner, StatusBadge } from "@/components";
import { useRunbookMutation, useStatusQuery } from "@/hooks/useOperationsData";
import { useSessionStore } from "@/stores/sessionStore";
import { formatDistanceToNow } from "date-fns";

export function DrillControlPage() {
  const statusQuery = useStatusQuery();
  const status = statusQuery.data;
  const mutation = useRunbookMutation();
  const sessionWindow = useSessionStore((state) => state.sessionWindow);

  const latestDrill = status?.runbook_history.find((entry) => entry.command === "drill");

  return (
    <div className="flex flex-col gap-6">
      {statusQuery.isError ? <ErrorBanner error={statusQuery.error} /> : null}

      <header className="card-surface flex flex-col gap-3">
        <h2 className="text-xl font-semibold text-neutral-100">
          Failover Drill Control / 故障演练控制
        </h2>
        <p className="text-sm text-neutral-300">
          Automate end-to-end failover drills with inline telemetry. 自动化执行故障演练并收集指标佐证。
        </p>
        {latestDrill ? (
          <div className="flex flex-wrap items-center gap-3 text-sm text-neutral-400">
            <StatusBadge
              status={latestDrill.exit_code === 0 ? "success" : "danger"}
              labelEn={latestDrill.exit_code === 0 ? "Drill Passed" : "Drill Failed"}
              labelZh={latestDrill.exit_code === 0 ? "演练通过" : "演练失败"}
            />
            <span>
              {formatDistanceToNow(new Date(latestDrill.finished_at), {
                addSuffix: true,
              })}
            </span>
          </div>
        ) : null}
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <ActionPanel
          titleEn="Execute Full Drill"
          titleZh="执行完整演练"
          descriptionEn="Start -> failover -> failback with health verification and latency capture."
          descriptionZh="执行启动-切换-回切全流程，自动校验健康与延迟指标。"
          actionLabelEn="Start Drill"
          actionLabelZh="启动演练"
          payload={{
            command: "drill",
            mode: "live",
            window: sessionWindow,
            profile: "live",
            reason: "Scheduled drill from console",
          }}
          confirmationMessage="Confirm executing drill sequence against the live stack? / 确认在生产栈执行完整演练？"
        />
        <ActionPanel
          titleEn="Health Check"
          titleZh="健康检查"
          descriptionEn="Run enforcement health check with remediation to validate live coverage."
          descriptionZh="执行 enforce 模式健康检查并在生产环境验证覆盖率。"
          actionLabelEn="Run Health Check"
          actionLabelZh="执行健康检查"
          payload={{
            command: "health_check",
            mode: "live",
            window: sessionWindow,
            profile: "live",
            enforce: true,
            reason: "Drill pre-flight health check",
          }}
        />
      </div>

      {mutation.isPending ? (
        <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 text-sm text-primary">
          Executing runbook action... / 正在执行 Runbook 操作...
        </div>
      ) : null}
    </div>
  );
}
