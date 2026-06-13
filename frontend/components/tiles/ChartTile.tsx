"use client";
import {
  ResponsiveContainer,
  AreaChart, Area,
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";

type ChartType = "line" | "bar" | "area" | "pie";

interface DataPoint {
  x?: string | number;
  y?: number;
  label?: string;
  value?: number;
  name?: string;
}

interface Config {
  chart_type?: ChartType;
  data?: DataPoint[];
  x_label?: string;
  y_label?: string;
  colors?: string[];
}

const DEFAULT_COLORS = ["#002EFF", "#16a34a", "#d97706", "#dc2626", "#7c3aed", "#0891b2"];

const TOOLTIP_STYLE = {
  contentStyle: {
    background: "#fff",
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    fontSize: 11,
    boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
  },
  labelStyle: { color: "#737373", marginBottom: 2 },
};

const AXIS_TICK = { fontSize: 10, fill: "var(--fm)" } as const;

export default function ChartTile({ config, isBig }: { config: Config; isBig?: boolean }) {
  const { chart_type = "line", data = [], colors = DEFAULT_COLORS } = config;
  const height = isBig ? 220 : 110;

  // Normalise: support {x,y} or {name,value} or {label,value}
  const normalised = data.map((d) => ({
    x: d.x ?? d.label ?? d.name ?? "",
    y: d.y ?? d.value ?? 0,
  }));

  if (!normalised.length) {
    return (
      <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, color: "var(--fm)" }}>
        No data
      </div>
    );
  }

  if (chart_type === "pie") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie data={normalised} dataKey="y" nameKey="x" cx="50%" cy="50%" outerRadius={height / 2 - 10} label={false}>
            {normalised.map((_, i) => (
              <Cell key={i} fill={colors[i % colors.length]} />
            ))}
          </Pie>
          <Tooltip {...TOOLTIP_STYLE} />
          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 10 }} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (chart_type === "bar") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={normalised} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
          <XAxis dataKey="x" tick={AXIS_TICK} tickLine={false} axisLine={false} />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={40} />
          <Tooltip {...TOOLTIP_STYLE} />
          <Bar dataKey="y" fill={colors[0]} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart_type === "area") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={normalised} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
          <defs>
            <linearGradient id="dc-area-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={colors[0]} stopOpacity={0.15} />
              <stop offset="95%" stopColor={colors[0]} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
          <XAxis dataKey="x" tick={AXIS_TICK} tickLine={false} axisLine={false} />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={40} />
          <Tooltip {...TOOLTIP_STYLE} />
          <Area type="monotone" dataKey="y" stroke={colors[0]} strokeWidth={2} fill="url(#dc-area-grad)" dot={false} activeDot={{ r: 4, fill: colors[0] }} />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // Default: line
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={normalised} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
        <XAxis dataKey="x" tick={AXIS_TICK} tickLine={false} axisLine={false} />
        <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={40} />
        <Tooltip {...TOOLTIP_STYLE} />
        <Line type="monotone" dataKey="y" stroke={colors[0]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
