import ReactECharts from "echarts-for-react";

const LABELS: Record<string, string> = {
  equity: "Акции",
  bonds: "Облигации",
  money_market: "Денежный рынок",
  gold: "Золото",
  cash: "Валюта",
  derivatives: "Срочный рынок",
  mixed: "Смешанные",
  other: "Прочее",
};

// Категориальная палитра, зафиксированная за классом актива (а не за
// позицией в списке): при синхронизации набор присутствующих классов может
// измениться, а цвет каждого конкретного класса должен оставаться прежним.
// Восемь оттенков в этом порядке и шаге под тёмную поверхность прошли
// проверку accessibility-валидатором dataviz (CVD-разделение, контраст с
// фоном приложения) — см. отчёт задачи 15.
const COLORS: Record<string, string> = {
  equity: "#3987e5",
  bonds: "#d95926",
  money_market: "#199e70",
  gold: "#c98500",
  cash: "#d55181",
  derivatives: "#008300",
  mixed: "#9085e9",
  other: "#e66767",
};

export function AllocationChart({ data }: { data: Record<string, string> }) {
  const entries = Object.entries(data).map(([key, value]) => ({
    name: LABELS[key] ?? key,
    value: Number.parseFloat(value),
    itemStyle: { color: COLORS[key] },
  }));

  if (entries.length === 0) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>
        Структура появится после первой успешной синхронизации и оценки позиций.
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12, marginBottom: 8 }}>Структура портфеля</div>
      <ReactECharts
        style={{ height: 260 }}
        option={{
          tooltip: { trigger: "item", valueFormatter: (v: number) => `${v.toLocaleString("ru-RU")} ₽` },
          legend: { bottom: 0, textStyle: { color: "#9aa5c4" } },
          series: [{
            type: "pie",
            radius: ["52%", "78%"],
            itemStyle: { borderColor: "#0f1424", borderWidth: 2 },
            label: { show: false },
            data: entries,
          }],
        }}
      />
    </div>
  );
}
