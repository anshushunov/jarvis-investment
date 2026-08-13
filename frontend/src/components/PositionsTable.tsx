import { BASE_CURRENCY, formatMoney, formatQuantity } from "../api/format";
import { Card, CardTitle } from "../ui/Card";
import { CardState } from "../ui/CardState";
import { Table, Td, Th } from "../ui/Table";
import { ChangeValue } from "./MoneyValue";
import type { PositionRow } from "../api/client";

// Цена брокера — не независимая оценка: тот же источник, с чьим снимком мы
// сверяемся. Молча показывать её наравне с биржевой нельзя.
function PriceSourceMark({ source }: { source: string | null }) {
  if (source !== "tbank") return null;
  return (
    <span title="Цена от брокера, не с биржи" className="ml-1 text-muted">
      ·бр
    </span>
  );
}

// Ограничение бумаги и блокировка количества — разные причины недоступности, и
// обе встречаются по отдельности. Значок один, подсказка разная: владельцу
// важно, можно ли распорядиться, но при разборе расхождений важно и почему.
function RestrictedMark({ restricted, blocked }: { restricted: boolean; blocked: string }) {
  const blockedQuantity = Number.parseFloat(blocked);
  if (!restricted && blockedQuantity === 0) return null;

  const title = restricted
    ? "Ни купить, ни продать: бумага ограничена в обороте"
    : `Заблокировано брокером: ${formatQuantity(blocked)} шт.`;

  return <span title={title} className="ml-1 text-amber">🔒</span>;
}

// Рублёвая оценка строки — та самая величина, которой позиция входит в
// совокупный капитал. Без неё позиция с ценой, но без курса показывала
// уверенное «1 000 $» и в капитал не попадала вовсе, а единственное
// предупреждение на экране называло причиной нехватку котировок — то есть не
// ту причину.
function BaseValue({ currency, marketValue, valueBase }: {
  currency: string;
  marketValue: string | null;
  valueBase: string | null;
}) {
  // Котировки нет — прочерк строкой выше уже всё сказал, и рублёвой оценки
  // взяться неоткуда по той же причине. Второй раз о том же не сообщаем.
  if (marketValue === null) return null;

  if (valueBase === null) {
    return (
      <div
        title={`Нет курса ${currency} к рублю: позиция не входит в совокупный капитал`}
        className="text-2xs text-amber"
      >
        нет курса
      </div>
    );
  }

  // Рубли в рублях — тот же самый ряд цифр во второй раз.
  if (currency.toUpperCase() === BASE_CURRENCY) return null;

  return (
    <div className="text-2xs text-muted">
      {formatMoney(valueBase, BASE_CURRENCY)}
    </div>
  );
}

export function PositionsTable({ rows, error, loading }: {
  rows: PositionRow[];
  error: string | null;
  loading: boolean;
}) {
  // Сбой запроса — не то же самое, что «позиций пока нет»: приглашение
  // «запустите синхронизацию» при реальном сбое сети было бы враньём.
  if (error) return <CardState kind="error">Не удалось загрузить позиции: {error}</CardState>;

  // Идущий запрос — тоже не «позиций пока нет». Сводка отвечает быстрее, и без
  // этой ветки заглушка успевала мелькнуть на долю секунды.
  if (loading) return <CardState kind="loading">Загрузка позиций…</CardState>;

  if (rows.length === 0) {
    return (
      <CardState kind="empty">Позиций пока нет — запустите синхронизацию с брокером.</CardState>
    );
  }

  return (
    <Card>
      <CardTitle>Позиции</CardTitle>
      <Table>
        <thead>
          <tr>
            <Th>Бумага</Th>
            <Th>Счёт</Th>
            <Th>Валюта</Th>
            <Th numeric>Количество</Th>
            <Th numeric>Средняя</Th>
            <Th numeric>Текущая</Th>
            <Th numeric>Стоимость</Th>
            <Th numeric>Результат</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            // isin+счёт различает строки уже по смыслу (один инструмент на
            // двух счетах — две разные позиции). Индекс остаётся добавкой к
            // ключу на случай данных, где и это совпадёт; порядок строк от
            // бэкенда стабилен.
            <tr key={`${row.isin}-${row.account}-${index}`}>
              <Td>
                <div>
                  {row.ticker ?? "—"}
                  <RestrictedMark restricted={row.restricted} blocked={row.blocked} />
                </div>
                <div className="text-2xs text-muted">{row.name}</div>
              </Td>
              {/* Счёт: при пяти счетах одного брокера один тикер давал
                  несколько визуально одинаковых строк. */}
              <Td><span className="text-xs text-muted">{row.account}</span></Td>
              {/* Валюта строки видна отдельной колонкой: без неё одинаковые
                  числа в разных валютах выглядели бы сопоставимыми. Ею
                  подписаны цена и стоимость ниже, но не средняя — та берёт
                  свою собственную валюту (см. average_price_currency ниже),
                  потому что у замещающих облигаций она отличается от валюты
                  котировки. */}
              <Td><span className="text-muted">{row.currency}</span></Td>
              <Td numeric>{formatQuantity(row.quantity)}</Td>
              {/* Средняя подписывается своей валютой, а не валютой котировки:
                  у замещающей облигации журнал знает рубли, а MOEX котирует её
                  в долларах, и рублёвое число под знаком доллара завышало
                  цифру в восемьдесят раз. Пустая средняя (бумаги пришли
                  переводом) даёт прочерк с подсказкой — formatMoney уже умеет
                  null, но молчаливый прочерк не объясняет причину. */}
              <Td numeric>
                <span title={row.cost_basis_known ? undefined
                    : "Себестоимость неизвестна: бумаги пришли переводом"}>
                  {formatMoney(row.average_price, row.average_price_currency)}
                </span>
              </Td>
              {/* Нет котировки — прочерк (formatMoney на null), а не «0 ₽»:
                  неизвестная стоимость и нулевая стоимость это разные вещи. */}
              <Td numeric>
                {formatMoney(row.last_price, row.currency)}
                <PriceSourceMark source={row.price_source} />
              </Td>
              {/* Стоимость в валюте строки, а под ней — в рублях: капитал
                  считается в рублях, и строка без рублёвой оценки обязана
                  отличаться от строки с ней. */}
              <Td numeric>
                {formatMoney(row.market_value, row.currency)}
                <BaseValue
                  currency={row.currency}
                  marketValue={row.market_value}
                  valueBase={row.value_base}
                />
              </Td>
              <Td numeric><ChangeValue percent={row.profit_percent} /></Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}
