import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Decision, ReconciliationRow } from "../api/client";
import { formatQuantity } from "../api/format";
import { DecisionPanel } from "./DecisionPanel";

const TEXT: Record<string, string> = {
  quantity_mismatch: "количество не совпадает",
  missing_in_ledger: "есть у брокера, но нет в журнале",
  missing_at_broker: "есть в журнале, но нет у брокера",
};

// Журнал решений идёт рядом с расхождениями, а не внутри них: расхождение,
// закрытое решением, исчезает — а пояснение владельца остаётся единственным
// ответом на вопрос «откуда это количество». Пока журнал был вложен в
// свёрнутый по умолчанию список, он пропадал вместе с последним расхождением,
// то есть ровно тогда, ради чего заводился GET /api/decisions.
export function ReconciliationBanner({ rows, error }: { rows: ReconciliationRow[]; error: string | null }) {
  return (
    <>
      {error ? <ReconciliationFailure error={error} /> : null}
      {!error && rows.length > 0 ? <ReconciliationSummary rows={rows} /> : null}
      <DecisionLog />
    </>
  );
}

// Сбой проверки — это не то же самое, что «расхождений нет»: молчание здесь
// читалось бы владельцем как «всё сошлось», хотя сверка просто не выполнена.
function ReconciliationFailure({ error }: { error: string }) {
  return (
    <div className="card" style={{ borderColor: "rgba(242,116,154,0.45)", background: "rgba(242,116,154,0.08)" }}>
      <div style={{ color: "var(--red)", fontWeight: 600 }}>Не удалось проверить расхождения с брокером</div>
      <div style={{ fontSize: 13, color: "var(--tx-2)", marginTop: 6 }}>
        {error}. Это не значит, что расхождений нет — сверка сейчас недоступна.
      </div>
    </div>
  );
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
                onClick={() => setOpen(open === `${row.account}-${row.isin}-${index}` ? null : `${row.account}-${row.isin}-${index}`)}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer",
                         color: "var(--amber)", font: "inherit", textDecoration: "underline" }}
              >
                разобрать
              </button>
              {row.suggestions.length > 0 && (
                <span title="Система нашла подходящую пару" style={{ marginLeft: 4 }}>💡</span>
              )}
              {open === `${row.account}-${row.isin}-${index}` && (
                <DecisionPanel row={row} onDone={() => setOpen(null)} />
              )}
            </div>
          ))}
          <div style={{ fontSize: 12, color: "var(--tx-2)", marginTop: 8 }}>
            Позиции не исправлены автоматически: за этим обычно стоят корпоративные действия —
            конвертации расписок, смены ISIN, дробления. Брокер не присылает их отдельной операцией.
          </div>
        </div>
      )}
    </div>
  );
}

// Отменить можно только подтверждённое решение и только не зеркальное: отмену
// отмены служба отвергает — своего следа в книге партий она не оставляет, и
// раскручивать было бы нечего (app/decisions/service.py, revert_decision).
// Кнопку, ведущую в заведомый отказ, показывать нечестно.
function isRevertable(decision: Decision): boolean {
  return decision.status === "CONFIRMED" && decision.reverts_id === null;
}

// Решения не исчезают вместе с расхождением, которое они закрыли: пояснение
// владельца — единственный источник ответа на вопрос «откуда это количество».
function DecisionLog() {
  const queryClient = useQueryClient();
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: api.decisions });
  const [reverting, setReverting] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  const revert = useMutation({
    mutationFn: ({ id, note: reason }: { id: number; note: string }) =>
      api.revertDecision(id, reason),
    onSuccess: () => {
      // Отмена меняет журнал, позиции и сверку разом — обновляем всё.
      queryClient.invalidateQueries();
      setReverting(null);
      setNote("");
    },
  });

  if (!decisions.data || decisions.data.length === 0) return null;

  function start(id: number) {
    setReverting(id);
    setNote("");
    setValidation(null);
    revert.reset();
  }

  function submit(id: number) {
    // Пояснение обязательно и при отмене: бэкенд отвергнет запрос без него, а
    // владелец узнает об этом только после круга по сети.
    if (note.trim() === "") {
      setValidation("Пояснение обязательно — через год причину отмены не восстановит никто.");
      return;
    }
    setValidation(null);
    revert.mutate({ id, note });
  }

  return (
    <div className="card">
      <div style={{ fontSize: 12, color: "var(--tx-2)", marginBottom: 4 }}>
        Уже разобрано: {decisions.data.length}
      </div>
      {decisions.data.map((decision) => (
        <div key={decision.id} style={{ fontSize: 12, color: "var(--tx-2)", padding: "2px 0" }}>
          {decision.account} · {decision.from_isin ?? "—"} → {decision.to_isin ?? "—"}
          {decision.status === "REVERTED" && " (отменено)"} — {decision.note}
          {isRevertable(decision) && reverting !== decision.id && (
            <>
              {" "}
              <button
                type="button"
                onClick={() => start(decision.id)}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer",
                         color: "var(--amber)", font: "inherit", textDecoration: "underline" }}
              >
                отменить решение №{decision.id}
              </button>
            </>
          )}
          {reverting === decision.id && (
            <div style={{ marginTop: 4, padding: 8, border: "1px solid var(--line)", borderRadius: 6 }}>
              <label style={{ display: "block" }}>
                Почему отменяем
                <textarea value={note} onChange={(event) => setNote(event.target.value)}
                          rows={2} style={{ display: "block", marginTop: 3, width: "100%" }} />
              </label>
              {validation && (
                <div style={{ color: "var(--red)", marginTop: 4 }}>{validation}</div>
              )}
              {revert.isError && (
                <div style={{ color: "var(--red)", marginTop: 4 }}>{(revert.error as Error).message}</div>
              )}
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <button type="button" onClick={() => submit(decision.id)} disabled={revert.isPending}>
                  {revert.isPending ? "Отменяем…" : "Отменить"}
                </button>
                <button type="button" onClick={() => setReverting(null)} disabled={revert.isPending}>
                  Не отменять
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
