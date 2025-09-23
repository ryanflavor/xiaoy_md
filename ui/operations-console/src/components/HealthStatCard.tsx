import clsx from "clsx";
import { Colors } from "@/styles/tokens";

export type HealthStatCardProps = {
  titleEn: string;
  titleZh: string;
  value: string;
  unit?: string;
  subtitle?: string;
  status?: "success" | "warning" | "danger" | "info";
  trend?: string;
  tooltip?: string;
};

const statusToColor: Record<NonNullable<HealthStatCardProps["status"]>, string> = {
  success: Colors.success,
  warning: Colors.warning,
  danger: Colors.danger,
  info: Colors.primary,
};

export function HealthStatCard({
  titleEn,
  titleZh,
  value,
  unit,
  subtitle,
  status = "info",
  trend,
  tooltip,
}: HealthStatCardProps) {
  return (
    <article
      className="card-surface flex flex-col gap-3"
      title={tooltip ?? `${titleEn} / ${titleZh}`}
    >
      <header className="flex items-center justify-between text-sm font-medium text-neutral-300">
        <span>
          {titleEn}
          <span className="ml-2 text-neutral-500">{titleZh}</span>
        </span>
        <span
          className={clsx("inline-flex items-center gap-1 text-xs", {
            "text-success": status === "success",
            "text-warning": status === "warning",
            "text-danger": status === "danger",
            "text-primary": status === "info",
          })}
        >
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: statusToColor[status] }}
          />
          {statusLabel(status)}
        </span>
      </header>
      <div className="flex items-baseline gap-2">
        <span className="text-4xl font-semibold text-neutral-100">{value}</span>
        {unit ? <span className="text-sm text-neutral-400">{unit}</span> : null}
      </div>
      {trend ? (
        <div className="text-xs text-neutral-400">{trend}</div>
      ) : null}
      {subtitle ? (
        <footer className="text-xs text-neutral-500">{subtitle}</footer>
      ) : null}
    </article>
  );
}

function statusLabel(status: HealthStatCardProps["status"]) {
  switch (status) {
    case "success":
      return "Healthy / 正常";
    case "warning":
      return "Warning / 预警";
    case "danger":
      return "Critical / 告警";
    default:
      return "Info / 信息";
  }
}
