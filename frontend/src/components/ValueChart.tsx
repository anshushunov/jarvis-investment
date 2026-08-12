import ReactECharts from "echarts-for-react";
import { formatDate } from "../api/format";
import { tokens } from "../design/tokens";
import { Card, CardTitle } from "../ui/Card";
import { CardState } from "../ui/CardState";
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
    return <CardState kind="error">Не удалось загрузить историю стоимости: {error}</CardState>;
  }

  // То же и для идущего запроса: пока история не пришла, «истории нет» —
  // неправда, а не осторожная формулировка.
  if (loading) return <CardState kind="loading">Загрузка истории…</CardState>;

  if (points.length === 0) {
    return (
      <CardState kind="empty">
        Истории пока нет: достройте её прогоном app.snapshots.backfill.
      </CardState>
    );
  }

  const values = points.map((point) => Number.parseFloat(point.total_value));
  const incomplete = points
    .map((point, index) => (isIncomplete(point) ? [index, values[index]] : null))
    .filter((item): item is number[] => item !== null);

  return (
    <Card>
      <CardTitle>Стоимость портфеля</CardTitle>
      <ReactECharts
        style={{ height: 260 }}
        option={{
          grid: { left: 60, right: 16, top: 16, bottom: 32 },
          // Та же функция форматирования даты, что и в шапке страницы —
          // подписи оси не должны расходиться по формату с остальным интерфейсом.
          xAxis: { type: "category", data: points.map((p) => formatDate(p.date) ?? p.date),
                   axisLine: { lineStyle: { color: tokens.chart.axis } } },
          yAxis: { type: "value", scale: true,
                   splitLine: { lineStyle: { color: tokens.chart.grid } },
                   axisLabel: { color: tokens.chart.label } },
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
              lineStyle: { color: tokens.chart.line, width: 2 },
              areaStyle: { color: tokens.chart.area },
              data: values,
            },
            {
              // Неполнота передаётся и цветом, и формой: спека системы требует,
              // чтобы факт и предположение различались, а цвет в одиночку не
              // различает их для того, кто его не видит.
              type: "scatter", symbol: "triangle", symbolSize: 8,
              itemStyle: { color: tokens.chart.incomplete },
              data: incomplete,
            },
          ],
        }}
      />
      {incomplete.length > 0 && (
        <div className="mt-2 text-xs text-muted">
          ▲ — дни, где оценены не все позиции: цены на эти бумаги нет ни на бирже, ни у брокера.
        </div>
      )}
    </Card>
  );
}
