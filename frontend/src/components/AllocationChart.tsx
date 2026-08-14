import ReactECharts from "echarts-for-react";
import { ASSET_CLASS_TITLES, BASE_CURRENCY, formatMoney } from "../api/format";
import { tokens } from "../design/tokens";
import { Card, CardTitle } from "../ui/Card";
import { CardState } from "../ui/CardState";

export function AllocationChart({ data }: {
  data: Record<string, string>;
}) {
  const entries = Object.entries(data).map(([key, value]) => ({
    // Металлы перечислены все четыре в ASSET_CLASS_TITLES (api/format.ts), а
    // не одно золото: METAL_CURRENCIES в аналитике бэкенда знает XAU, XAG, XPT
    // и XPD, и остаток в любом из них заводит собственный класс актива. Без
    // подписи сектор рисуется сырым ключом («silver» латиницей посреди
    // русского графика).
    name: ASSET_CLASS_TITLES[key] ?? key,
    // value — только геометрия сектора, число здесь разрешено (écharts не
    // умеет строки). raw — исходная строка от бэкенда, идёт в подсказку через
    // ту же formatMoney, что и весь остальной интерфейс, а не через число.
    value: Number.parseFloat(value),
    raw: value,
    itemStyle: { color: tokens.assetClass[key as keyof typeof tokens.assetClass] },
  }));

  if (entries.length === 0) {
    return (
      <CardState kind="empty">
        Структура появится после первой успешной синхронизации и оценки позиций.
      </CardState>
    );
  }

  return (
    <Card>
      <CardTitle>Структура портфеля</CardTitle>
      <ReactECharts
        style={{ height: 260 }}
        option={{
          tooltip: {
            trigger: "item",
            // Подсказка идёт владельцу на экран, а не в геометрию графика —
            // сумма форматируется через formatMoney из исходной строки
            // (params.data.raw), а не пересчётом уже сконвертированного числа.
            // Разбивка полностью пересчитана в рубли (см. portfolio_overview
            // в аналитике бэкенда) — валюта здесь всегда базовая.
            formatter: (params: { marker: string; name: string; data: { raw: string } }) =>
              `${params.marker}${params.name}: ${formatMoney(params.data.raw, BASE_CURRENCY)}`,
          },
          legend: { bottom: 0, textStyle: { color: tokens.chart.label } },
          series: [{
            type: "pie",
            radius: ["52%", "78%"],
            itemStyle: { borderColor: tokens.chart.pieBorder, borderWidth: 2 },
            label: { show: false },
            data: entries,
          }],
        }}
      />
    </Card>
  );
}
