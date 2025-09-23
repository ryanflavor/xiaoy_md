import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import dayjs from "dayjs";
import type { TimeseriesPoint } from "@/services/types";

export type MetricChartProps = {
  titleEn: string;
  titleZh: string;
  unit?: string | null;
  points: TimeseriesPoint[];
};

export function MetricChart({ titleEn, titleZh, unit, points }: MetricChartProps) {
  return (
    <div className="card-surface h-72">
      <header className="mb-4 flex items-baseline justify-between">
        <h3 className="text-lg font-semibold text-neutral-100">
          {titleEn}
          <span className="ml-2 text-sm text-neutral-500">{titleZh}</span>
        </h3>
        {unit ? <span className="text-xs text-neutral-400">{unit}</span> : null}
      </header>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={points.map((point) => ({
            ...point,
            timestampLabel: dayjs(point.timestamp).format("HH:mm"),
          }))}
        >
          <defs>
            <linearGradient id="metricGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#38BDF8" stopOpacity={0.9} />
              <stop offset="95%" stopColor="#38BDF8" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2b3d" />
          <XAxis dataKey="timestampLabel" stroke="#64748B" tickLine={false} />
          <YAxis stroke="#64748B" tickLine={false} width={60} />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1E293B",
              borderRadius: 12,
              border: "1px solid #38BDF8",
            }}
            labelFormatter={(value) => `时间 Time: ${value}`}
            formatter={(value: number) => [value, unit ?? ""]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke="#38BDF8"
            fill="url(#metricGradient)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
