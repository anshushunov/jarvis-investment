import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  ASSET_CLASS_TITLES,
  BASE_CURRENCY,
  formatMoney,
  isZeroAmount,
  subtractMoney,
  sumMoney,
} from "../api/format";
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

// Ключ строки «Деньги и металлы» в разрезе по классам — тот же, что задаёт
// бэкенд (MONEY_ROW_CLASS в app/returns/breakdown.py). Нужен здесь, чтобы
// назвать словами, из чего состоит разница между итогом таблицы по бумагам и
// прибылью портфеля.
const MONEY_ROW_CLASS = "cash_and_metals";

// Почему сумма строк таблицы по бумагам не равна прибыли портфеля.
//
// Тождество фазы — «бумаги + деньги + Прочее = прибыль портфеля» (дизайн,
// раздел 7), и до сих пор его сходимость видел только тот, кто запускал прогон
// в терминале. На экране расхождение обязано объясняться словами, а не
// оставаться невязкой: в таблице по бумагам нет строки «Деньги и металлы» (она
// в разрезе по классам), а у бумаги без цены, курса или истории прибыль не
// посчитана вовсе и в сумму не входит.
// Экспортируется ради теста: фраза под таблицей — чистая функция от ответа, и
// проверять её рендером целой страницы значило бы поднимать react-query ради
// одной строки текста.
export function instrumentsFooter(returns: Returns) {
  const total = sumMoney([
    ...returns.by_instrument.map((row) => row.profit),
    returns.unattributed.profit,
  ]);
  const gap = subtractMoney(returns.portfolio.profit, total);
  const unknown = returns.by_instrument.filter((row) => row.profit === null).length;
  const money = returns.by_asset_class.find((row) => row.asset_class === MONEY_ROW_CLASS);

  const totals = `Итог по таблице ${formatMoney(total, BASE_CURRENCY)}`
    + ` · прибыль портфеля ${formatMoney(returns.portfolio.profit, BASE_CURRENCY)}`;
  if (isZeroAmount(gap)) return `${totals} — сходится до копейки.`;

  const causes = [
    money === undefined
      ? null
      : `деньги и металлы ${formatMoney(money.profit, BASE_CURRENCY)}`
        + " (своя строка в таблице по классам активов)",
    unknown === 0
      ? null
      : `${unknown} бумаг, у которых прибыль не посчитана: нет цены, курса`
        + " или истории — причина названа в самой строке",
  ].filter((cause) => cause !== null);

  const explained = causes.length === 0
    ? "причина не названа — так быть не должно, это дефект расчёта"
    : causes.join(" и ");
  return `${totals}. Разница ${formatMoney(gap, BASE_CURRENCY)} — ${explained}.`;
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
        footer={instrumentsFooter(data)}
        rows={[
          ...data.by_instrument.map((row) => ({
            // Ключ — instrument_id, а не тикер: тикеры не уникальны
            // (редомициляция даёт пару с одним тикером), и React получал бы
            // дубли ключей на живых 252 бумагах. Порядок строк задан бэкендом
            // (app/returns/breakdown.py, _row_order) — экран его не меняет.
            key: `instrument-${row.instrument_id}`, title: row.name, xirr: row.xirr,
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
