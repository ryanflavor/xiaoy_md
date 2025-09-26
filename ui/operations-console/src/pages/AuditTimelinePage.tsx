import { useMemo } from "react";
import { useStatusQuery } from "@/hooks/useOperationsData";
import { ErrorBanner } from "@/components";
import { isoTimestamp } from "@/services/apiClient";

export function AuditTimelinePage() {
  const statusQuery = useStatusQuery();
  const status = statusQuery.data;
  const history = useMemo(() => status?.runbook_history ?? [], [status]);

  return (
    <div className="flex flex-col gap-6">
      {statusQuery.isError ? <ErrorBanner error={statusQuery.error} /> : null}

      <header className="card-surface">
        <h2 className="text-xl font-semibold text-neutral-100">
          Audit Timeline / 审计时间线
        </h2>
        <p className="mt-2 text-sm text-neutral-400">
          Review all console-triggered runbook actions with exit codes and timestamps. 审阅所有通过控制台触发的 Runbook 操作。
        </p>
      </header>
      <section className="card-surface">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm text-neutral-200">
            <thead className="text-xs uppercase text-neutral-500">
              <tr>
                <th className="px-4 py-3">Command / 操作</th>
                <th className="px-4 py-3">Window / 时段</th>
                <th className="px-4 py-3">Profile / 账户</th>
                <th className="px-4 py-3">Mode / 模式</th>
                <th className="px-4 py-3">Exit / 退出码</th>
                <th className="px-4 py-3">Completed / 完成时间</th>
                <th className="px-4 py-3">Reason / 原因</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-neutral-500">
                    No runbook actions yet / 暂无操作
                  </td>
                </tr>
              ) : (
                [...history]
                  .sort(
                    (a, b) =>
                      new Date(b.finished_at).getTime() - new Date(a.finished_at).getTime()
                  )
                  .map((entry) => (
                    <tr key={entry.request_id} className="border-t border-surface/60">
                      <td className="px-4 py-3">{entry.command}</td>
                      <td className="px-4 py-3">{entry.window}</td>
                      <td className="px-4 py-3">{entry.config ?? entry.profile}</td>
                      <td className="px-4 py-3">{entry.mode}</td>
                      <td className="px-4 py-3 text-primary">{entry.exit_code}</td>
                      <td className="px-4 py-3">{isoTimestamp(entry.finished_at)}</td>
                      <td className="px-4 py-3 text-neutral-400">
                        {String(entry.metadata?.reason ?? "--")}
                      </td>
                    </tr>
                  ))
              )}
            </tbody>
          </table>
        </div>
        {history.length ? (
          <div className="mt-4 text-xs text-neutral-500">
            Raw audit logs available via backend `/ops/runbooks/execute` responses. 可通过后台接口获取完整日志。
          </div>
        ) : null}
      </section>
    </div>
  );
}
