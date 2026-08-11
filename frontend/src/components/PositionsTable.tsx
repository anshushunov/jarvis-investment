import { BASE_CURRENCY, formatMoney, formatQuantity } from "../api/format";
import { ChangeValue } from "./MoneyValue";
import type { PositionRow } from "../api/client";

// Цена брокера — не независимая оценка: тот же источник, с чьим снимком мы
// сверяемся. Молча показывать её наравне с биржевой нельзя.
function PriceSourceMark({ source }: { source: string | null }) {
  if (source !== "tbank") return null;
  return (
    <span title="Цена от брокера, не с биржи" style={{ color: "var(--tx-2)", marginLeft: 4 }}>
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

  return <span title={title} style={{ color: "var(--amber)", marginLeft: 4 }}>🔒</span>;
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
        style={{ color: "var(--amber)", fontSize: 11.5 }}
      >
        нет курса
      </div>
    );
  }

  // Рубли в рублях — тот же самый ряд цифр во второй раз.
  if (currency.toUpperCase() === BASE_CURRENCY) return null;

  return (
    <div style={{ color: "var(--tx-2)", fontSize: 11.5 }}>
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
  if (error) {
    return (
      <div className="card" style={{ color: "var(--red)", fontSize: 13 }}>
        Не удалось загрузить позиции: {error}
      </div>
    );
  }

  // Идущий запрос — тоже не «позиций пока нет». Сводка отвечает быстрее, и без
  // этой ветки заглушка успевала мелькнуть на долю секунды.
  if (loading) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>Загрузка позиций…</div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>
        Позиций пока нет — запустите синхронизацию с брокером.
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12, marginBottom: 10 }}>Позиции</div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ color: "var(--tx-2)", textAlign: "right" }}>
            <th style={{ textAlign: "left", paddingBottom: 8 }}>Бумага</th>
            <th style={{ textAlign: "left" }}>Счёт</th>
            <th style={{ textAlign: "left" }}>Валюта</th>
            <th>Количество</th>
            <th>Средняя</th>
            <th>Текущая</th>
            <th>Стоимость</th>
            <th>Результат</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            // isin+счёт различает строки уже по смыслу (один инструмент на
            // двух счетах — две разные позиции). Индекс остаётся добавкой к
            // ключу на случай данных, где и это совпадёт; порядок строк от
            // бэкенда стабилен.
            <tr key={`${row.isin}-${row.account}-${index}`} style={{ borderTop: "1px solid var(--line)", textAlign: "right" }}>
              <td style={{ textAlign: "left", padding: "9px 0" }}>
                <div>
                  {row.ticker ?? "—"}
                  <RestrictedMark restricted={row.restricted} blocked={row.blocked} />
                </div>
                <div style={{ color: "var(--tx-2)", fontSize: 11.5 }}>{row.name}</div>
              </td>
              {/* Счёт: при пяти счетах одного брокера один тикер давал
                  несколько визуально одинаковых строк. */}
              <td style={{ textAlign: "left", color: "var(--tx-2)", fontSize: 12 }}>{row.account}</td>
              {/* Валюта строки видна отдельной колонкой: без неё одинаковые
                  числа в разных валютах выглядели бы сопоставимыми. Ею
                  подписаны цена и стоимость ниже, но не средняя — та берёт
                  свою собственную валюту (см. average_price_currency ниже),
                  потому что у замещающих облигаций она отличается от валюты
                  котировки. */}
              <td style={{ textAlign: "left", color: "var(--tx-2)" }}>{row.currency}</td>
              <td>{formatQuantity(row.quantity)}</td>
              {/* Средняя подписывается своей валютой, а не валютой котировки:
                  у замещающей облигации журнал знает рубли, а MOEX котирует её
                  в долларах, и рублёвое число под знаком доллара завышало
                  цифру в восемьдесят раз. Пустая средняя (бумаги пришли
                  переводом) даёт прочерк с подсказкой — formatMoney уже умеет
                  null, но молчаливый прочерк не объясняет причину. */}
              <td title={row.cost_basis_known ? undefined
                  : "Себестоимость неизвестна: бумаги пришли переводом"}>
                {formatMoney(row.average_price, row.average_price_currency)}
              </td>
              {/* Нет котировки — прочерк (formatMoney на null), а не «0 ₽»:
                  неизвестная стоимость и нулевая стоимость это разные вещи. */}
              <td>
                {formatMoney(row.last_price, row.currency)}
                <PriceSourceMark source={row.price_source} />
              </td>
              {/* Стоимость в валюте строки, а под ней — в рублях: капитал
                  считается в рублях, и строка без рублёвой оценки обязана
                  отличаться от строки с ней. */}
              <td>
                {formatMoney(row.market_value, row.currency)}
                <BaseValue
                  currency={row.currency}
                  marketValue={row.market_value}
                  valueBase={row.value_base}
                />
              </td>
              <td><ChangeValue percent={row.profit_percent} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
