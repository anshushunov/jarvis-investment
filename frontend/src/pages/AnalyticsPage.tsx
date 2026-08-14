import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ASSET_CLASS_TITLES } from "../api/format";
import { api, type Returns, type ReturnsPeriod } from "../api/client";
import type { BreakdownRow } from "../components/ReturnsBreakdown";
import { ReturnsBreakdown } from "../components/ReturnsBreakdown";
import { ReturnsCoverageNotice } from "../components/ReturnsCoverageNotice";
import { ReturnsSummary } from "../components/ReturnsSummary";
import { CardState } from "../ui/CardState";
import { SegmentedControl } from "../ui/SegmentedControl";

const PERIODS: { value: ReturnsPeriod; label: string }[] = [
  { value: "all", label: "Всё время" },
  { value: "12m", label: "12 месяцев" },
  { value: "ytd", label: "С начала года" },
];

// «Прочее» — комиссии, налоги и возвраты без привязки к бумаге (unattributed
// в ответе). Добавляется последней строкой разреза по бумагам: без неё сумма
// строк не сходится с прибылью портфеля на эту величину (живой замер
// 14.08.2026 — около −107 тыс. ₽), а владелец вправе видеть, куда делись
// деньги. xirr и value у неё намеренно не «неизвестны», а «не бывают»: это не
// бумага и не позиция — ставки и стоимости в этом смысле у неё нет.
function unattributedRow(returns: Returns): BreakdownRow {
  return {
    key: "unattributed",
    title: "Прочее (комиссии и налоги без бумаги)",
    xirr: null,
    profit: returns.unattributed.profit,
    value: null,
    reason: "unattributed",
  };
}

export function AnalyticsPage() {
  // Период — состояние экрана, а не часть адреса: то же решение, что на
  // «Портфеле» с переключателем графика.
  const [period, setPeriod] = useState<ReturnsPeriod>("all");
  const returns = useQuery({
    queryKey: ["returns", period],
    queryFn: () => api.returns(period),
  });

  if (returns.isPending) return <CardState kind="loading">Загрузка…</CardState>;
  if (returns.isError) {
    return <CardState kind="error">{(returns.error as Error).message}</CardState>;
  }

  const data = returns.data;
  const daysTotal = data.coverage.days_total;

  return (
    <div className="grid gap-3.5">
      <SegmentedControl options={PERIODS} value={period} onChange={setPeriod} />
      <ReturnsSummary returns={data} />

      <ReturnsBreakdown
        title="По счетам"
        daysTotal={daysTotal}
        rows={data.by_account.map((row) => ({
          key: row.title, title: row.title, xirr: row.xirr, twr: row.twr,
          chain_days: row.chain_days, profit: row.profit, value: row.value,
          reason: row.reason,
        }))}
      />

      <ReturnsBreakdown
        title="По классам активов"
        daysTotal={daysTotal}
        rows={data.by_asset_class.map((row) => ({
          key: row.asset_class, title: ASSET_CLASS_TITLES[row.asset_class] ?? row.asset_class,
          xirr: row.xirr, twr: row.twr, chain_days: row.chain_days,
          profit: row.profit, value: row.value, reason: row.reason,
        }))}
      />

      <ReturnsBreakdown
        title="По бумагам"
        rows={[
          ...data.by_instrument.map((row) => ({
            key: `${row.ticker ?? row.name}`, title: row.name, xirr: row.xirr,
            profit: row.profit, value: row.value, reason: row.reason,
            closed: row.closed, unrealized: row.unrealized, fx_part: row.fx_part,
          })),
          unattributedRow(data),
        ]}
      />

      <ReturnsCoverageNotice coverage={data.coverage} />
    </div>
  );
}
