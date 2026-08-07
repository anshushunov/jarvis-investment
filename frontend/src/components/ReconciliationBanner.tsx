import { formatQuantity } from "../api/format";
import type { ReconciliationRow } from "../api/client";

const TEXT: Record<string, string> = {
  quantity_mismatch: "количество не совпадает",
  missing_in_ledger: "есть у брокера, но нет в журнале",
  missing_at_broker: "есть в журнале, но нет у брокера",
};

export function ReconciliationBanner({ rows }: { rows: ReconciliationRow[] }) {
  if (rows.length === 0) return null;

  return (
    <div className="card" style={{ borderColor: "rgba(232,176,75,0.45)", background: "rgba(232,176,75,0.08)" }}>
      <div style={{ color: "var(--amber)", fontWeight: 600, marginBottom: 8 }}>
        Расхождения с данными брокера: {rows.length}
      </div>
      {rows.map((row) => (
        <div key={row.isin} style={{ fontSize: 13, color: "var(--tx-2)", padding: "3px 0" }}>
          {row.isin}: {TEXT[row.status] ?? row.status} — в журнале {formatQuantity(row.ledger_quantity)},
          у брокера {formatQuantity(row.broker_quantity)}
        </div>
      ))}
      <div style={{ fontSize: 12, color: "var(--tx-2)", marginTop: 8 }}>
        Позиции не исправлены автоматически: вероятно, не хватает истории операций за более ранний период.
      </div>
    </div>
  );
}
