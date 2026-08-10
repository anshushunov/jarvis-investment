import { coverageWarning } from "../api/coverage";
import { BASE_CURRENCY, formatMoney } from "../api/format";
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
  if (overview.restricted_value === "0.0000") return null;

  return (
    <div style={{ margin: "6px 0 0", fontSize: 12.5, color: "var(--tx-2)" }}>
      Недоступно к продаже{" "}
      <span style={{ color: "var(--amber)" }}>
        {formatMoney(overview.restricted_value, BASE_CURRENCY)}
      </span>
    </div>
  );
}

// Совокупный капитал считается только по той части портфеля, которую удалось
// перевести в рубли. Пока это не весь портфель, сама цифра об этом не говорит
// ничего — предупреждение должно стоять вплотную к ней, читаться, а не теряться
// мелким шрифтом, и называть настоящую причину: нет котировок и нет курсов —
// это разные поломки, и чинятся они по-разному.
function CoverageNotice({ overview }: { overview: Overview }) {
  const warning = coverageWarning(overview);
  if (warning === null) return null;

  const style = {
    margin: "10px 0 0", padding: "7px 10px", borderRadius: 8, fontSize: 13,
  } as const;

  if (warning.kind === "rates") {
    return (
      <div style={{ ...style, background: "rgba(224,108,108,0.14)", color: "var(--red)" }}>
        Нет курса к рублю: {warning.currencies.join(", ")}. Всё, что в этих валютах, в
        сумму не входит — ни бумаги, ни остатки, ни металлы. Курсы подтянутся сами
        (ЦБ, ежедневно в 12:10 МСК; металлы — с MOEX) или вручную — см. README,
        «Курсы, цены и оценка капитала». В рублях посчитаны {warning.valued} позиций
        из {warning.total}.
      </div>
    );
  }

  return (
    <div style={{ ...style, background: "rgba(232,176,75,0.14)", color: "var(--amber)" }}>
      Часть портфеля не оценена: цены есть только для {warning.valued} позиций из{" "}
      {warning.total}. Остальные в эту сумму не входят.
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
