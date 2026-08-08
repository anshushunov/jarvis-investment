import { BASE_CURRENCY, formatMoney, hasForeignCurrency } from "../api/format";
import { MoneyValue } from "./MoneyValue";
import type { Overview, SyncRunResult } from "../api/client";

const STATUS_LABEL: Record<string, string> = {
  success: "синхронизирован",
  failed: "ошибка синхронизации",
};

function foreignTotals(byCurrency: Record<string, string>): [string, string][] {
  return Object.entries(byCurrency).filter(([currency]) => currency !== BASE_CURRENCY);
}

// Позиции в валютах, отличных от рубля, в совокупный капитал не входят:
// пересчёта по курсам пока нет, а складывать разные деньги под знаком рубля
// нельзя. Показываем их отдельным итогом по каждой валюте.
function ForeignCurrencyTotals({ byCurrency }: { byCurrency: Record<string, string> }) {
  const foreign = foreignTotals(byCurrency);
  if (foreign.length === 0) return null;

  return (
    <div style={{ margin: "10px 0 0", fontSize: 12.5, color: "var(--tx-2)" }}>
      Вне рублёвого итога (пересчёта по курсам пока нет):{" "}
      {foreign.map(([currency, amount], index) => (
        <span key={currency}>
          {index > 0 && ", "}
          <span style={{ color: "var(--tx-1, inherit)" }}>{formatMoney(amount, currency)}</span>
        </span>
      ))}
    </div>
  );
}

// Совокупный капитал считается только по позициям, для которых есть котировка.
// Пока оценены не все, сама цифра об этом не говорит ничего — предупреждение
// должно стоять вплотную к ней и читаться, а не теряться мелким шрифтом.
function CoverageNotice({ overview }: { overview: Overview }) {
  const { valued_positions: valued, positions_total: total } = overview;
  if (total === 0 || valued === total) return null;

  return (
    <div
      style={{
        margin: "10px 0 0", padding: "7px 10px", borderRadius: 8,
        background: "rgba(232,176,75,0.14)", color: "var(--amber)", fontSize: 13,
      }}
    >
      Часть портфеля не оценена: цены есть только для {valued} позиций из {total}.
      Остальные в эту сумму не входят.
    </div>
  );
}

export function SummaryCard({ overview, onSync, syncing, syncResult, syncErrorMessage }: {
  overview: Overview;
  onSync: () => void;
  syncing: boolean;
  syncResult: SyncRunResult[] | null;
  syncErrorMessage: string | null;
}) {
  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12 }}>
        Совокупный капитал
        {hasForeignCurrency(overview.position_currencies) ? " · рублёвая часть" : ""}
      </div>
      <div style={{ fontSize: 34, fontWeight: 650, letterSpacing: "-0.025em", margin: "6px 0 0" }}>
        <MoneyValue amount={overview.total_value} currency={BASE_CURRENCY} />
      </div>
      <ForeignCurrencyTotals byCurrency={overview.by_currency} />
      <CoverageNotice overview={overview} />
      <button
        onClick={onSync}
        disabled={syncing}
        style={{
          marginTop: 14,
          border: "1px solid var(--line)", borderRadius: 9, padding: "7px 14px",
          background: "rgba(123,156,255,0.14)", color: "var(--blue)", cursor: "pointer",
        }}
      >
        {syncing ? "Синхронизация…" : "Обновить из Т-Банка"}
      </button>

      {syncErrorMessage && (
        <div style={{ color: "var(--red)", fontSize: 13, marginTop: 12 }}>{syncErrorMessage}</div>
      )}

      {syncResult && (
        <div style={{ marginTop: 14, display: "grid", gap: 6 }}>
          {syncResult.map((run) => (
            <div key={run.account} style={{ fontSize: 12.5 }}>
              <span style={{ color: run.status === "success" ? "var(--green)" : "var(--red)" }}>
                {run.status === "success" ? "✓" : "✕"}
              </span>{" "}
              <span style={{ color: "var(--tx-2)" }}>{run.account}:</span>{" "}
              {STATUS_LABEL[run.status] ?? run.status}
              {run.error && <div style={{ color: "var(--tx-2)", marginLeft: 18 }}>{run.error}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
