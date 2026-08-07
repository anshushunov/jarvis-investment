import ReactECharts from "echarts-for-react";
import type { HistoryPoint } from "../api/client";

export function ValueChart({ points }: { points: HistoryPoint[] }) {
  if (points.length < 2) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>
        График появится, когда накопится хотя бы два ежедневных снимка стоимости.
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12, marginBottom: 8 }}>Стоимость портфеля</div>
      <ReactECharts
        style={{ height: 260 }}
        option={{
          grid: { left: 60, right: 16, top: 16, bottom: 32 },
          xAxis: { type: "category", data: points.map((p) => p.date),
                   axisLine: { lineStyle: { color: "#3a4763" } } },
          yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: "#1c2438" } },
                   axisLabel: { color: "#9aa5c4" } },
          tooltip: { trigger: "axis" },
          series: [{
            type: "line", smooth: true, showSymbol: false,
            lineStyle: { color: "#638cff", width: 2 },
            areaStyle: { color: "rgba(99,140,255,0.18)" },
            data: points.map((p) => Number.parseFloat(p.total_value)),
          }],
        }}
      />
    </div>
  );
}
