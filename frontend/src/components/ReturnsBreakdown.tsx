import { BASE_CURRENCY, formatMoney, fractionToPercent } from "../api/format";
import { Badge } from "../ui/Badge";
import { Card, CardTitle } from "../ui/Card";
import { CardState } from "../ui/CardState";
import { Table, Td, Th } from "../ui/Table";
import { ChangeValue } from "./MoneyValue";

// Причина отсутствия числа — словами, тем же принципом, что и в
// ReturnsSummary.tsx, но своим словарём: там текст объясняет одну крупную
// цифру портфеля, здесь — компактную строку таблицы, и словарь у строки
// разреза шире. `reason` в схеме один на строку и может объяснять разное в
// зависимости от того, что у строки вообще существует:
//
// - у строки периметра (счёт, класс актива) — это MetricOut.reason: почему
//   нет XIRR и/или TWR (app/returns/metrics.py::reason());
// - у строки бумаги (InstrumentReturnOut) — это либо причина отсутствия
//   profit/value (нет цены/курса на конец или начало периода), либо причина,
//   по которой не разложилась НЕреализованная прибыль (app/returns/fx_split.py)
//   — какая из двух, решает бэкенд по приоритету (см. breakdown.py), и
//   различать их на экране незачем: причина одна на строку, и показывается
//   она одна.
const REASONS: Record<string, string> = {
  no_flows: "движения за период не было",
  no_solution: "потоков недостаточно для расчёта ставки",
  no_full_days: "не хватает цен, чтобы измерить хотя бы один день",
  series_gaps: "в истории стоимости есть разрывы",
  no_history: "истории за период нет",
  empty_period: "период пуст: не прошло ни дня",
  cash: "доходности у денег и металлов нет — проценты приходят отдельными записями",
  no_cost_basis: "бумага пришла переводом, себестоимость неизвестна",
  no_price: "нет котировки на нужную дату",
  no_rate: "нет курса валюты",
  currency_mismatch: "расчёты и котировка в разных валютах",
  // Синтетическая причина строки «Прочее» — она не бумага и не периметр
  // доходности: у комиссий и налогов без привязки к позиции нет ни ставки, ни
  // стоимости в том смысле, в каком они есть у остальных строк.
  unattributed: "не бумага — сумма комиссий и налогов без привязки к позиции, ставки и стоимости у неё нет",
};

export interface BreakdownRow {
  key: string;
  title: string;
  xirr: string | null;
  // TWR и chain_days есть только у строк периметра — счёта и класса актива
  // (MetricOut). У бумаги TWR не считается вовсе (дизайн, раздел 4.3: снимок
  // не хранит дневной ряд по отдельной бумаге) — оба поля тогда не передаются
  // совсем, а не равны null: undefined значит «у строки такого не бывает»,
  // null — «TWR не посчитан, но мог бы быть». Путать их значило бы нарисовать
  // колонку TWR там, где ей взяться неоткуда.
  twr?: string | null;
  // Сколько дней цепочка TWR ЭТОЙ строки реально измерила. У каждой строки
  // своя цепочка и свой обрыв: TWR счёта 7 и TWR класса bonds посчитаны на
  // разных кусках истории, и без этого числа рядом с каждым значением они
  // выглядели бы посчитанными на одном отрезке, а это не так (см. daysTotal
  // у ReturnsBreakdown ниже).
  chain_days?: number | null;
  profit: string | null;
  value: string | null;
  reason: string | null;
  closed?: boolean;
  // Нереализованная прибыль открытых партий и её разложение на части — только
  // у строк по бумагам, и это НЕ то же самое, что profit за период (дизайн,
  // раздел 4.4): у бумаги с частичными продажами profit включает ещё и
  // реализованный результат, которого разложение не видит по устройству.
  unrealized?: string | null;
  fx_part?: string | null;
}

export function ReturnsBreakdown({ title, rows, daysTotal }: {
  title: string;
  rows: BreakdownRow[];
  // Общая длина периода отчёта — знаменатель для chain_days каждой строки
  // (Returns.coverage.days_total, одна цифра на весь отчёт). Нужен только
  // когда в таблице есть колонка TWR.
  daysTotal?: number;
}) {
  const showTwr = rows.some((row) => row.twr !== undefined);
  const showFx = rows.some((row) => row.fx_part !== undefined);

  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      {rows.length === 0 ? (
        <CardState kind="empty">Данных за период нет.</CardState>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Название</Th>
              <Th numeric>{showTwr ? "XIRR" : "Доходность"}</Th>
              {showTwr && <Th numeric>TWR</Th>}
              <Th numeric>Прибыль</Th>
              {showFx && (
                <Th numeric>
                  <span>из них валютная</span>
                  <div className="text-2xs text-muted">нереализованной, не прибыли периода</div>
                </Th>
              )}
              <Th numeric>Стоимость</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <Td>
                  {row.title}
                  {row.closed === true && (
                    <span className="ml-1.5"><Badge>закрыта</Badge></span>
                  )}
                  {row.reason !== null && (
                    <div className="text-2xs text-muted">{REASONS[row.reason] ?? row.reason}</div>
                  )}
                </Td>
                <Td numeric>
                  <ChangeValue percent={row.xirr === null ? null : fractionToPercent(row.xirr)} />
                </Td>
                {showTwr && (
                  <Td numeric>
                    <ChangeValue
                      percent={row.twr === undefined || row.twr === null ? null : fractionToPercent(row.twr)}
                    />
                    {row.chain_days !== undefined && row.chain_days !== null && daysTotal !== undefined && (
                      <div className="text-2xs text-muted">измерено {row.chain_days} из {daysTotal} дней</div>
                    )}
                  </Td>
                )}
                <Td numeric>{formatMoney(row.profit, BASE_CURRENCY)}</Td>
                {showFx && <Td numeric>{formatMoney(row.fx_part ?? null, BASE_CURRENCY)}</Td>}
                <Td numeric>{formatMoney(row.value, BASE_CURRENCY)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}
