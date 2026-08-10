import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type DecisionInput, type ReconciliationRow } from "../api/client";
import { formatQuantity } from "../api/format";

const KINDS = [
  { value: "CONVERSION", label: "Конвертация: одна бумага стала другой" },
  { value: "ADJUSTMENT", label: "Поправить количество вручную" },
  { value: "ACCEPTED_AS_IS", label: "Принять как есть, расхождение объяснено" },
] as const;

type Kind = (typeof KINDS)[number]["value"];

// Дата события по умолчанию — сегодня. Конвертация случилась когда-то раньше,
// и владелец обычно знает когда; поле редактируемое именно поэтому.
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function DecisionPanel({ row, onDone }: {
  row: ReconciliationRow;
  onDone: () => void;
}) {
  const suggestion = row.suggestions[0] ?? null;
  const queryClient = useQueryClient();

  const [kind, setKind] = useState<Kind>(suggestion ? "CONVERSION" : "ADJUSTMENT");
  const [fromIsin, setFromIsin] = useState(suggestion?.from_isin ?? row.isin ?? "");
  const [fromQuantity, setFromQuantity] = useState(suggestion?.from_quantity ?? "");
  const [toIsin, setToIsin] = useState(suggestion?.to_isin ?? "");
  const [toQuantity, setToQuantity] = useState(suggestion?.to_quantity ?? "");
  const [effectiveAt, setEffectiveAt] = useState(today());
  const [note, setNote] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: (body: DecisionInput) => api.createDecision(body),
    onSuccess: () => {
      queryClient.invalidateQueries();
      onDone();
    },
  });

  function confirm(status: "CONFIRMED" | "REJECTED") {
    if (note.trim() === "") {
      // Проверяем до запроса: бэкенд то же самое отвергнет, но владелец
      // узнает об этом только после круга по сети.
      setValidation("Пояснение обязательно — через год причину не восстановит никто.");
      return;
    }
    setValidation(null);
    submit.mutate({
      account: row.account,
      kind,
      status,
      from_isin: kind === "ACCEPTED_AS_IS" ? null : fromIsin || null,
      from_quantity: kind === "ACCEPTED_AS_IS" ? null : fromQuantity || null,
      to_isin: kind === "CONVERSION" || kind === "ADJUSTMENT" ? toIsin || null : null,
      to_quantity: kind === "CONVERSION" || kind === "ADJUSTMENT" ? toQuantity || null : null,
      effective_at: `${effectiveAt}T00:00:00Z`,
      note,
    });
  }

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid var(--line)", borderRadius: 6 }}>
      {suggestion && (
        <div style={{ fontSize: 12.5, marginBottom: 8 }}>
          Похоже на конвертацию: {formatQuantity(suggestion.from_quantity)} шт.{" "}
          {suggestion.from_isin} → {formatQuantity(suggestion.to_quantity)} шт.{" "}
          {suggestion.to_isin}
          {suggestion.blocked_fully && (
            <div style={{ color: "var(--amber)", fontSize: 11.5 }}>
              Бумага-получатель заблокирована у брокера целиком — частый след
              корпоративного действия.
            </div>
          )}
          {suggestion.ambiguous && (
            <div style={{ color: "var(--amber)", fontSize: 11.5 }}>
              Подходящих бумаг несколько: выбор за вами, система не угадывает.
            </div>
          )}
        </div>
      )}

      <label style={{ display: "block", fontSize: 12, marginBottom: 6 }}>
        Что произошло
        <select value={kind} onChange={(event) => setKind(event.target.value as Kind)}
                style={{ display: "block", marginTop: 3, width: "100%" }}>
          {KINDS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>

      {kind !== "ACCEPTED_AS_IS" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 6 }}>
          {kind === "CONVERSION" && (
            <>
              <label style={{ fontSize: 12 }}>
                Из какой бумаги
                <input value={fromIsin} onChange={(e) => setFromIsin(e.target.value)}
                       style={{ display: "block", width: "100%" }} />
              </label>
              <label style={{ fontSize: 12 }}>
                Сколько списать
                <input value={fromQuantity} onChange={(e) => setFromQuantity(e.target.value)}
                       style={{ display: "block", width: "100%" }} />
              </label>
            </>
          )}
          <label style={{ fontSize: 12 }}>
            В какую бумагу
            <input value={toIsin} onChange={(e) => setToIsin(e.target.value)}
                   style={{ display: "block", width: "100%" }} />
          </label>
          <label style={{ fontSize: 12 }}>
            Сколько зачислить
            <input value={toQuantity} onChange={(e) => setToQuantity(e.target.value)}
                   style={{ display: "block", width: "100%" }} />
          </label>
        </div>
      )}

      <label style={{ display: "block", fontSize: 12, marginBottom: 6 }}>
        Дата события
        <input type="date" value={effectiveAt}
               onChange={(event) => setEffectiveAt(event.target.value)}
               style={{ display: "block", marginTop: 3 }} />
      </label>

      <label style={{ display: "block", fontSize: 12, marginBottom: 6 }}>
        Пояснение
        <textarea value={note} onChange={(event) => setNote(event.target.value)}
                  rows={2} style={{ display: "block", marginTop: 3, width: "100%" }} />
      </label>

      {validation && (
        <div style={{ color: "var(--red)", fontSize: 12, marginBottom: 6 }}>{validation}</div>
      )}
      {submit.isError && (
        <div style={{ color: "var(--red)", fontSize: 12, marginBottom: 6 }}>
          {(submit.error as Error).message}
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" onClick={() => confirm("CONFIRMED")}
                disabled={submit.isPending}>
          {submit.isPending ? "Отправляем…" : "Подтвердить"}
        </button>
        {suggestion && (
          <button type="button" onClick={() => confirm("REJECTED")}
                  disabled={submit.isPending}>
            Это не конвертация
          </button>
        )}
        <button type="button" onClick={onDone} disabled={submit.isPending}>
          Отмена
        </button>
      </div>
    </div>
  );
}
