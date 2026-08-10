import { formatMoney } from "../api/format";
import type { CashRow } from "../api/client";

// Металлы приходят от брокера валютными кодами: XAU — золото в граммах.
// Подписывать их знаком валюты нельзя, у граммов его нет.
const METAL_LABEL: Record<string, string> = {
  XAU: "золото, г",
  XAG: "серебро, г",
  XPT: "платина, г",
  XPD: "палладий, г",
};

export function CashCard({ rows, error }: { rows: CashRow[]; error: string | null }) {
  if (error) {
    return <div className="card"><div style={{ color: "var(--red)" }}>{error}</div></div>;
  }
  if (rows.length === 0) {
    return (
      <div className="card">
        <div style={{ color: "var(--tx-2)", fontSize: 12 }}>Денежные остатки</div>
        <div style={{ marginTop: 8, color: "var(--tx-2)", fontSize: 13 }}>
          Остатков нет. Они появятся после синхронизации.
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12 }}>Денежные остатки</div>
      <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
        {rows.map((row) => (
          <div
            key={`${row.account}-${row.currency}`}
            style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}
          >
            <span style={{ color: "var(--tx-2)" }}>
              {row.account}
              {METAL_LABEL[row.currency] ? ` · ${METAL_LABEL[row.currency]}` : ""}
            </span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              {METAL_LABEL[row.currency]
                ? row.amount.replace(/\.?0+$/, "").replace(".", ",")
                : formatMoney(row.amount, row.currency)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
