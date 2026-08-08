import { formatMoney, formatQuantity } from "../api/format";
import { ChangeValue } from "./MoneyValue";
import type { PositionRow } from "../api/client";

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
                <div>{row.ticker ?? "—"}</div>
                <div style={{ color: "var(--tx-2)", fontSize: 11.5 }}>{row.name}</div>
              </td>
              {/* Счёт: при пяти счетах одного брокера один тикер давал
                  несколько визуально одинаковых строк. */}
              <td style={{ textAlign: "left", color: "var(--tx-2)", fontSize: 12 }}>{row.account}</td>
              {/* Валюта строки видна отдельной колонкой: суммы ниже подписаны
                  ею, а не рублём, и без явной колонки одинаковые числа в
                  разных валютах выглядели бы сопоставимыми. */}
              <td style={{ textAlign: "left", color: "var(--tx-2)" }}>{row.currency}</td>
              <td>{formatQuantity(row.quantity)}</td>
              <td>{formatMoney(row.average_price, row.currency)}</td>
              {/* Нет котировки — прочерк (formatMoney на null), а не «0 ₽»:
                  неизвестная стоимость и нулевая стоимость это разные вещи. */}
              <td>{formatMoney(row.last_price, row.currency)}</td>
              <td>{formatMoney(row.market_value, row.currency)}</td>
              <td><ChangeValue percent={row.profit_percent} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
