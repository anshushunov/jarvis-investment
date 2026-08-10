import { formatMoney, formatQuantity } from "../api/format";
import type { CashRow } from "../api/client";

// Металлы приходят от брокера валютными кодами: XAU — золото в граммах.
// Подписывать их знаком валюты нельзя, у граммов его нет.
const METAL_LABEL: Record<string, string> = {
  XAU: "золото, г",
  XAG: "серебро, г",
  XPT: "платина, г",
  XPD: "палладий, г",
};

// Заблокированная часть остатка — та же причина недоступности, что и замок у
// позиций в PositionsTable, только для денег. Значок тот же (согласованный
// язык по всему интерфейсу), а не отдельная строка: она бы держала место на
// каждом счету, даже когда блокировки нет, а у владельца сейчас она нулевая
// везде. Молчим, пока заблокированного нет — ноль это не новость.
function BlockedMark({ blocked, currency }: { blocked: string; currency: string }) {
  const blockedQuantity = Number.parseFloat(blocked);
  if (blockedQuantity === 0) return null;

  const amount = METAL_LABEL[currency] ? `${formatQuantity(blocked)} г` : formatMoney(blocked, currency);
  return (
    <span title={`Заблокировано брокером: ${amount}`} style={{ color: "var(--amber)", marginLeft: 4 }}>
      🔒
    </span>
  );
}

export function CashCard({ rows, error, loading }: {
  rows: CashRow[];
  error: string | null;
  loading: boolean;
}) {
  if (error) {
    return <div className="card"><div style={{ color: "var(--red)" }}>{error}</div></div>;
  }

  // Идущий запрос — не то же самое, что «остатков нет»: без этого признака
  // заглушка про синхронизацию успевала мелькнуть, пока ответ ещё не пришёл,
  // хотя остатки на счетах есть и вот-вот приедут (тот же класс лжи, что уже
  // чинили для PositionsTable и ValueChart на этой странице).
  if (loading) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>Загрузка остатков…</div>
    );
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
              {METAL_LABEL[row.currency] ? formatQuantity(row.amount) : formatMoney(row.amount, row.currency)}
              <BlockedMark blocked={row.blocked} currency={row.currency} />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
