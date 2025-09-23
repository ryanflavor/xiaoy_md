import clsx from "clsx";

export type StatusBadgeProps = {
  status: "success" | "warning" | "danger" | "info";
  labelEn: string;
  labelZh: string;
};

export function StatusBadge({ status, labelEn, labelZh }: StatusBadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium",
        {
          "bg-success/15 text-success": status === "success",
          "bg-warning/15 text-warning": status === "warning",
          "bg-danger/15 text-danger": status === "danger",
          "bg-primary/15 text-primary": status === "info",
        }
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {labelEn} / {labelZh}
    </span>
  );
}
