import { BASE_CURRENCY, formatMoney, isPositiveAmount } from "../api/format";
import { CoverageNotice } from "./CoverageNotice";
import { MoneyValue } from "./MoneyValue";
import type { Overview, SyncRunResult } from "../api/client";

const STATUS_LABEL: Record<string, string> = {
  success: "синхронизирован",
  failed: "ошибка синхронизации",
};

// Из чего складывается капитал. Одна общая цифра не отвечает на вопрос,
// изменился портфель или просто пришли деньги на счёт.
function CapitalParts({ overview }: { overview: Overview }) {
  return (
    <div style={{ margin: "10px 0 0", fontSize: 12.5, color: "var(--tx-2)" }}>
      Бумаги <span style={{ color: "var(--tx-1, inherit)" }}>
        {formatMoney(overview.securities_value, BASE_CURRENCY)}
      </span>
      {" · деньги "}
      <span style={{ color: "var(--tx-1, inherit)" }}>
        {formatMoney(overview.cash_value, BASE_CURRENCY)}
      </span>
    </div>
  );
}

// Недоступное входит в капитал — брокер считает так же. Но распорядиться им
// нельзя, и знать об этом нужно рядом с самой цифрой: у владельца больше
// двадцати таких позиций, это заметная доля портфеля.
function RestrictedNotice({ overview }: { overview: Overview }) {
  // Плашка имеет смысл только у положительной суммы. Ноль сообщать не о чем, а
  // отрицательное «недоступно» достижимо у короткой позиции с блокировкой:
  // обязательство стоит отрицательных денег, и «Недоступно к продаже −1 000 ₽»
  // читалось бы как ошибка расчёта. Сравнение строки с «0.0000» ловило только
  // ноль.
  if (!isPositiveAmount(overview.restricted_value)) return null;

  return (
    <div style={{ margin: "6px 0 0", fontSize: 12.5, color: "var(--tx-2)" }}>
      Недоступно к продаже{" "}
      <span style={{ color: "var(--amber)" }}>
        {formatMoney(overview.restricted_value, BASE_CURRENCY)}
      </span>
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
      <div style={{ color: "var(--tx-2)", fontSize: 12 }}>Совокупный капитал</div>
      <div style={{ fontSize: 34, fontWeight: 650, letterSpacing: "-0.025em", margin: "6px 0 0" }}>
        <MoneyValue amount={overview.total_value} currency={BASE_CURRENCY} />
      </div>
      <CapitalParts overview={overview} />
      <RestrictedNotice overview={overview} />
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
