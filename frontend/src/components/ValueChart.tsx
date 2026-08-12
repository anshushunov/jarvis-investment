import ReactECharts from "echarts-for-react";
import { formatDate } from "../api/format";
import type { HistoryPoint } from "../api/client";

// Точка неполна, когда оценены не все позиции. Неизвестное покрытие (null у
// снимков, снятых до достройки) неполнотой не считается: объявить их неполными
// — такое же враньё, как объявить полными.
function isIncomplete(point: HistoryPoint): boolean {
  return (
    point.valued_positions !== null &&
    point.positions_total !== null &&
    point.valued_positions < point.positions_total
  );
}

export function ValueChart({ points, error, loading }: {
  points: HistoryPoint[];
  error: string | null;
  loading: boolean;
}) {
  // Сбой запроса — не то же самое, что «истории ещё нет»: заглушка про
  // накопление снимков при реальном сбое сети была бы враньём.
  if (error) {
    return (
      <div className="card" style={{ color: "var(--red)", fontSize: 13 }}>
        Не удалось загрузить историю стоимости: {error}
      </div>
    );
  }

  // То же и для идущего запроса: пока история не пришла, «истории нет» —
  // неправда, а не осторожная формулировка.
  if (loading) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>Загрузка истории…</div>
    );
  }

  if (points.length === 0) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>
        Истории пока нет: достройте её прогоном app.snapshots.backfill.
      </div>
    );
  }

  const values = points.map((point) => Number.parseFloat(point.total_value));
  const incomplete = points
    .map((point, index) => (isIncomplete(point) ? [index, values[index]] : null))
    .filter((item): item is number[] => item !== null);

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
          tooltip: {
            trigger: "axis",
            // Только дата и сумма. Покрытие и список неоценённых бумаг отсюда
            // убраны намеренно: подсказка следует за курсором и перекрывает
            // половину экрана, а перечень из десятка названий читать в ней
            // всё равно невозможно. Сам факт неполноты передаёт метка на
            // линии, разбираться с составом — не задача графика.
            formatter: (params: Array<{ dataIndex: number }>) => {
              const point = points[params[0].dataIndex];
              const value = Number.parseFloat(point.total_value).toLocaleString("ru-RU", {
                maximumFractionDigits: 0,
              });
              return `${formatDate(point.date) ?? point.date}<br/>${value} ₽`;
            },
          },
          series: [
            {
              type: "line", smooth: true, showSymbol: false,
              lineStyle: { color: "#638cff", width: 2 },
              areaStyle: { color: "rgba(99,140,255,0.18)" },
              data: values,
            },
            {
              // Неполнота передаётся и цветом, и формой: спека системы требует,
              // чтобы факт и предположение различались, а цвет в одиночку не
              // различает их для того, кто его не видит.
              type: "scatter", symbol: "triangle", symbolSize: 8,
              itemStyle: { color: "#e2b93b" },
              data: incomplete,
            },
          ],
        }}
      />
      {incomplete.length > 0 && (
        <div style={{ color: "var(--tx-2)", fontSize: 12, marginTop: 8 }}>
          ▲ — дни, где оценены не все позиции: цены на эти бумаги нет ни на бирже, ни у брокера.
        </div>
      )}
    </div>
  );
}
