import ReactECharts from "echarts-for-react";
import { formatDate } from "../api/format";
import type { HistoryPoint } from "../api/client";

export function ValueChart({ points, error, loading }: {
  points: HistoryPoint[];
  error: string | null;
  loading: boolean;
}) {
  // Сбой запроса — не то же самое, что «снимков ещё не накопилось»:
  // заглушка про накопление снимков при реальном сбое сети была бы враньём.
  if (error) {
    return (
      <div className="card" style={{ color: "var(--red)", fontSize: 13 }}>
        Не удалось загрузить историю стоимости: {error}
      </div>
    );
  }

  // То же и для идущего запроса: пока история не пришла, «снимков ещё нет» —
  // неправда, а не осторожная формулировка.
  if (loading) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>Загрузка истории…</div>
    );
  }

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
          // Та же функция форматирования даты, что и в шапке страницы —
          // подписи оси не должны расходиться по формату с остальным интерфейсом.
          xAxis: { type: "category", data: points.map((p) => formatDate(p.date) ?? p.date),
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
