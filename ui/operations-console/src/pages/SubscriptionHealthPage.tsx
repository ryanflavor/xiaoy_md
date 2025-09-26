import { useStatusQuery } from "@/hooks/useOperationsData";
import { ErrorBanner, StatusBadge } from "@/components";
import { isoTimestamp } from "@/services/apiClient";

export function SubscriptionHealthPage() {
  const statusQuery = useStatusQuery();
  const status = statusQuery.data;
  const health = status?.last_health;

  const missing = health?.missing_contracts ?? [];
  const stalled = health?.stalled_contracts ?? [];

  return (
    <div className="flex flex-col gap-6">
      {statusQuery.isError ? <ErrorBanner error={statusQuery.error} /> : null}

      <header className="card-surface flex flex-col gap-3">
        <h2 className="text-xl font-semibold text-neutral-100">
          Subscription Health / 订阅健康
        </h2>
        {health ? (
          <div className="flex flex-wrap items-center gap-3 text-sm text-neutral-300">
            <StatusBadge
              status={health.exit_code === 0 ? "success" : "warning"}
              labelEn={`Exit ${health.exit_code}`}
              labelZh={`退出码 ${health.exit_code}`}
            />
            <span>
              Generated / 生成时间: {isoTimestamp(health.generated_at)}
            </span>
            <span>
              Coverage / 覆盖率: {health.coverage_ratio?.toFixed(4) ?? "--"}
            </span>
          </div>
        ) : (
          <p className="text-sm text-neutral-400">No health data yet / 暂无健康数据</p>
        )}
      </header>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="card-surface">
          <h3 className="mb-3 text-lg font-semibold text-neutral-100">
            Missing Contracts / 缺失合约
          </h3>
          {missing.length === 0 ? (
            <p className="text-sm text-neutral-400">All contracts subscribed / 已全部订阅</p>
          ) : (
            <ul className="max-h-64 space-y-2 overflow-y-auto text-sm text-warning">
              {missing.map((symbol) => (
                <li key={symbol} className="rounded border border-warning/30 bg-warning/10 px-3 py-2">
                  {symbol}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card-surface">
          <h3 className="mb-3 text-lg font-semibold text-neutral-100">
            Stalled Streams / 卡顿合约
          </h3>
          {stalled.length === 0 ? (
            <p className="text-sm text-neutral-400">No stalled streams / 无卡顿流</p>
          ) : (
            <ul className="max-h-64 space-y-3 overflow-y-auto text-sm text-neutral-200">
              {stalled.map((entry, idx) => (
                <li key={`${entry.symbol ?? idx}-${idx}`} className="rounded border border-danger/30 bg-danger/10 px-3 py-2">
                  <div className="font-medium text-danger">
                    {entry.symbol ?? "Unknown"} ({entry.severity})
                  </div>
                  <div className="text-xs text-neutral-300">
                    Lag / 延迟: {entry.lag_seconds ?? "--"}s • Subscription ID: {entry.subscription_id}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="card-surface">
        <h3 className="mb-3 text-lg font-semibold text-neutral-100">
          Warnings & Errors / 警告与错误
        </h3>
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <h4 className="mb-2 text-sm font-semibold text-warning">Warnings / 警告</h4>
            {health?.warnings?.length ? (
              <ul className="space-y-2 text-sm text-warning">
                {health.warnings.map((item, idx) => (
                  <li key={idx} className="rounded border border-warning/30 bg-warning/10 px-3 py-2">
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-neutral-400">No warnings / 无警告</p>
            )}
          </div>
          <div>
            <h4 className="mb-2 text-sm font-semibold text-danger">Errors / 错误</h4>
            {health?.errors?.length ? (
              <ul className="space-y-2 text-sm text-danger">
                {health.errors.map((item, idx) => (
                  <li key={idx} className="rounded border border-danger/30 bg-danger/10 px-3 py-2">
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-neutral-400">No errors / 无错误</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
