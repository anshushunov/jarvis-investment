import { formatQuantity } from "../api/format";
import type { ReconciliationRow } from "../api/client";

const TEXT: Record<string, string> = {
  quantity_mismatch: "количество не совпадает",
  missing_in_ledger: "есть у брокера, но нет в журнале",
  missing_at_broker: "есть в журнале, но нет у брокера",
};

export function ReconciliationBanner({ rows, error }: { rows: ReconciliationRow[]; error: string | null }) {
  // Сбой проверки — это не то же самое, что «расхождений нет»: молчание здесь
  // читалось бы владельцем как «всё сошлось», хотя сверка просто не выполнена.
  if (error) {
    return (
      <div className="card" style={{ borderColor: "rgba(242,116,154,0.45)", background: "rgba(242,116,154,0.08)" }}>
        <div style={{ color: "var(--red)", fontWeight: 600 }}>Не удалось проверить расхождения с брокером</div>
        <div style={{ fontSize: 13, color: "var(--tx-2)", marginTop: 6 }}>
          {error}. Это не значит, что расхождений нет — сверка сейчас недоступна.
        </div>
      </div>
    );
  }

  if (rows.length === 0) return null;

  return (
    <div className="card" style={{ borderColor: "rgba(232,176,75,0.45)", background: "rgba(232,176,75,0.08)" }}>
      <div style={{ color: "var(--amber)", fontWeight: 600, marginBottom: 8 }}>
        Расхождения с данными брокера: {rows.length}
      </div>
      {rows.map((row, index) => (
        // Сверка считается по каждому счёту отдельно: один и тот же ISIN может
        // дать две строки на двух разных счетах — ключ обязан учитывать счёт,
        // а строка обязана показывать, о каком счёте речь (тот же класс бага,
        // что был найден и исправлен в таблице позиций).
        <div key={`${row.account}-${row.isin}-${index}`} style={{ fontSize: 13, color: "var(--tx-2)", padding: "3px 0" }}>
          {row.account} · {row.isin}: {TEXT[row.status] ?? row.status} — в журнале {formatQuantity(row.ledger_quantity)},
          у брокера {formatQuantity(row.broker_quantity)}
        </div>
      ))}
      <div style={{ fontSize: 12, color: "var(--tx-2)", marginTop: 8 }}>
        Позиции не исправлены автоматически: вероятно, не хватает истории операций за более ранний период.
      </div>
    </div>
  );
}
