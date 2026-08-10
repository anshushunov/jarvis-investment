import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { ReconciliationRow } from "../api/client";
import { formatQuantity } from "../api/format";
import { DecisionPanel } from "./DecisionPanel";

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

  return <ReconciliationSummary rows={rows} />;
}

// Свёрнут по умолчанию: развёрнутый список занимал весь первый экран и
// выталкивал сам портфель ниже сгиба. Число расхождений при этом видно
// всегда — прятать его нельзя, иначе владелец не узнает, что сверка что-то
// нашла.
function ReconciliationSummary({ rows }: { rows: ReconciliationRow[] }) {
  const [expanded, setExpanded] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="card" style={{ borderColor: "rgba(232,176,75,0.45)", background: "rgba(232,176,75,0.08)" }}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        style={{
          display: "flex", alignItems: "center", gap: 8, width: "100%",
          background: "none", border: "none", padding: 0, cursor: "pointer",
          color: "var(--amber)", fontWeight: 600, font: "inherit", textAlign: "left",
        }}
      >
        <span aria-hidden="true" style={{ fontSize: 11 }}>{expanded ? "▼" : "▶"}</span>
        <span>Расхождения с данными брокера: {rows.length}</span>
        <span style={{ fontSize: 13, fontWeight: 400, color: "var(--tx-2)" }}>
          {expanded ? "скрыть" : "показать"}
        </span>
      </button>

      {expanded && (
        <div style={{ marginTop: 8 }}>
          {rows.map((row, index) => (
            // Сверка считается по каждому счёту отдельно: один и тот же ISIN может
            // дать две строки на двух разных счетах — ключ обязан учитывать счёт,
            // а строка обязана показывать, о каком счёте речь (тот же класс бага,
            // что был найден и исправлен в таблице позиций).
            <div key={`${row.account}-${row.isin}-${index}`} style={{ fontSize: 13, color: "var(--tx-2)", padding: "3px 0" }}>
              {row.account} · {row.isin}: {TEXT[row.status] ?? row.status} — в журнале {formatQuantity(row.ledger_quantity)},
              у брокера {formatQuantity(row.broker_quantity)}
              {" "}
              <button
                type="button"
                onClick={() => setOpen(open === `${row.account}-${row.isin}` ? null : `${row.account}-${row.isin}`)}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer",
                         color: "var(--amber)", font: "inherit", textDecoration: "underline" }}
              >
                разобрать
              </button>
              {row.suggestions.length > 0 && (
                <span title="Система нашла подходящую пару" style={{ marginLeft: 4 }}>💡</span>
              )}
              {open === `${row.account}-${row.isin}` && (
                <DecisionPanel row={row} onDone={() => setOpen(null)} />
              )}
            </div>
          ))}
          <div style={{ fontSize: 12, color: "var(--tx-2)", marginTop: 8 }}>
            Позиции не исправлены автоматически: за этим обычно стоят корпоративные действия —
            конвертации расписок, смены ISIN, дробления. Брокер не присылает их отдельной операцией.
          </div>
          <DecisionLog />
        </div>
      )}
    </div>
  );
}

// Решения не исчезают вместе с расхождением, которое они закрыли: пояснение
// владельца — единственный источник ответа на вопрос «откуда это количество».
function DecisionLog() {
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: api.decisions });

  if (!decisions.data || decisions.data.length === 0) return null;

  return (
    <div style={{ marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 8 }}>
      <div style={{ fontSize: 12, color: "var(--tx-2)", marginBottom: 4 }}>
        Уже разобрано: {decisions.data.length}
      </div>
      {decisions.data.map((decision) => (
        <div key={decision.id} style={{ fontSize: 12, color: "var(--tx-2)", padding: "2px 0" }}>
          {decision.account} · {decision.from_isin ?? "—"} → {decision.to_isin ?? "—"}
          {decision.status === "REVERTED" && " (отменено)"} — {decision.note}
        </div>
      ))}
    </div>
  );
}
