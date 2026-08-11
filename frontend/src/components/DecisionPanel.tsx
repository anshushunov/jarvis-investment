import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type DecisionInput, type ReconciliationRow, type Suggestion } from "../api/client";
import { formatQuantity } from "../api/format";

const KINDS = [
  { value: "CONVERSION", label: "Конвертация: одна бумага стала другой" },
  { value: "ADJUSTMENT", label: "Поправить количество вручную" },
  { value: "ACCEPTED_AS_IS", label: "Принять как есть, расхождение объяснено" },
] as const;

type Kind = (typeof KINDS)[number]["value"];
type Direction = "CREDIT" | "DEBIT";

// Дата события по умолчанию — сегодня. Конвертация случилась когда-то раньше,
// и владелец обычно знает когда; поле редактируемое именно поэтому.
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function DecisionPanel({ row, onDone }: {
  row: ReconciliationRow;
  onDone: () => void;
}) {
  const suggestions = row.suggestions;
  // Гипотеза считается решённой автоматически только когда она единственная
  // и сам бэкенд не пометил её неоднозначной. У ambiguous-группы этот признак
  // стоит на каждом кандидате, включая тот единственный, что попал в список
  // именно этой строки: у него есть конкуренты на другой стороне, которых
  // отсюда не видно, — выбор всё равно остаётся за владельцем (см. докстринг
  // backend/app/decisions/suggestions.py про цену «правдоподобного» выбора).
  const certainSuggestion = suggestions.length === 1 && !suggestions[0].ambiguous ? suggestions[0] : null;
  const needsChoice = suggestions.length > 0 && certainSuggestion === null;
  const queryClient = useQueryClient();

  const [selectedSuggestion, setSelectedSuggestion] = useState<Suggestion | null>(certainSuggestion);
  const [kind, setKind] = useState<Kind>(suggestions.length > 0 ? "CONVERSION" : "ADJUSTMENT");
  // Направление поправки: корректировка описывает ровно одну сторону
  // (зачисление или списание) — бэкенд отвергает решение, где заполнены обе
  // или ни одной (app/decisions/service.py, _validate).
  const [direction, setDirection] = useState<Direction>("CREDIT");
  const [fromIsin, setFromIsin] = useState(
    certainSuggestion?.from_isin ?? (suggestions.length === 0 ? row.isin ?? "" : ""),
  );
  const [fromQuantity, setFromQuantity] = useState(certainSuggestion?.from_quantity ?? "");
  const [toIsin, setToIsin] = useState(certainSuggestion?.to_isin ?? "");
  const [toQuantity, setToQuantity] = useState(certainSuggestion?.to_quantity ?? "");
  // Себестоимость всей зачисляемой партии, если владелец её знает. Пусто —
  // партия помечается неизвестной себестоимостью, и по позиции не
  // показываются ни средняя цена, ни доходность (backend/app/decisions/
  // service.py, _generate_entries).
  const [costBasis, setCostBasis] = useState("");
  const [effectiveAt, setEffectiveAt] = useState(today());
  const [note, setNote] = useState("");
  const [validation, setValidation] = useState<string | null>(null);
  // Отклонение спрашивается дважды: оно необратимо. Отклонённая пара глушится
  // навсегда (backend/app/decisions/suggestions.py, _rejected_pairs), а отмену
  // служба даёт только подтверждённым решениям — один ошибочный клик, и
  // гипотеза больше никогда не предложится.
  const [rejecting, setRejecting] = useState(false);

  const submit = useMutation({
    mutationFn: (body: DecisionInput) => api.createDecision(body),
    onSuccess: () => {
      queryClient.invalidateQueries();
      onDone();
    },
  });

  // Кандидат подставляется в форму только по явному клику владельца — до
  // этого момента поля формы пусты, ни один вариант не выбран за него.
  function chooseSuggestion(candidate: Suggestion) {
    setSelectedSuggestion(candidate);
    setKind("CONVERSION");
    setFromIsin(candidate.from_isin);
    setFromQuantity(candidate.from_quantity);
    setToIsin(candidate.to_isin);
    setToQuantity(candidate.to_quantity);
  }

  // Смена вида решения обязана убрать значения полей, которые вид больше не
  // показывает: иначе они остаются в состоянии и невидимо уходят в запрос —
  // например, «сколько списать» из гипотезы конвертации доезжало бы до
  // корректировки, у которой на экране видно только поле зачисления.
  function changeKind(next: Kind) {
    setKind(next);
    if (next === "CONVERSION" && selectedSuggestion) {
      setFromIsin(selectedSuggestion.from_isin);
      setFromQuantity(selectedSuggestion.from_quantity);
      setToIsin(selectedSuggestion.to_isin);
      setToQuantity(selectedSuggestion.to_quantity);
      return;
    }
    setFromIsin(next === "CONVERSION" ? (row.isin ?? "") : "");
    setFromQuantity("");
    setToIsin("");
    setToQuantity("");
    setCostBasis("");
  }

  // Тот же принцип при смене направления корректировки: поле стороны, что
  // перестала быть видна, не должно унести в запрос значение, введённое для
  // другой стороны.
  function changeDirection(next: Direction) {
    setDirection(next);
    setFromIsin("");
    setFromQuantity("");
    setToIsin("");
    setToQuantity("");
    setCostBasis("");
  }

  function confirm(status: "CONFIRMED" | "REJECTED") {
    if (note.trim() === "") {
      // Проверяем до запроса: бэкенд то же самое отвергнет, но владелец
      // узнает об этом только после круга по сети.
      setValidation("Пояснение обязательно — через год причину не восстановит никто.");
      return;
    }
    setValidation(null);

    // В запрос идёт только то, что видно на экране для текущего вида решения
    // (и, для корректировки, для текущего направления) — скрытые поля не
    // подмешиваются, даже если в состоянии остался их старый текст.
    let payloadFromIsin: string | null = null;
    let payloadFromQuantity: string | null = null;
    let payloadToIsin: string | null = null;
    let payloadToQuantity: string | null = null;
    let payloadCostBasis: string | null = null;

    if (kind === "CONVERSION") {
      payloadFromIsin = fromIsin || null;
      payloadFromQuantity = fromQuantity || null;
      payloadToIsin = toIsin || null;
      payloadToQuantity = toQuantity || null;
    } else if (kind === "ADJUSTMENT") {
      if (direction === "DEBIT") {
        payloadFromIsin = fromIsin || null;
        payloadFromQuantity = fromQuantity || null;
      } else {
        payloadToIsin = toIsin || null;
        payloadToQuantity = toQuantity || null;
        payloadCostBasis = costBasis || null;
      }
    }

    submit.mutate({
      account: row.account,
      kind,
      status,
      from_isin: payloadFromIsin,
      from_quantity: payloadFromQuantity,
      to_isin: payloadToIsin,
      to_quantity: payloadToQuantity,
      cost_basis: payloadCostBasis,
      effective_at: `${effectiveAt}T00:00:00Z`,
      note,
    });
  }

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid var(--line)", borderRadius: 6 }}>
      {certainSuggestion && (
        <div style={{ fontSize: 12.5, marginBottom: 8 }}>
          Похоже на конвертацию: {formatQuantity(certainSuggestion.from_quantity)} шт.{" "}
          {certainSuggestion.from_isin} → {formatQuantity(certainSuggestion.to_quantity)} шт.{" "}
          {certainSuggestion.to_isin}
          {certainSuggestion.blocked_fully && (
            <div style={{ color: "var(--amber)", fontSize: 11.5 }}>
              Бумага-получатель заблокирована у брокера целиком — частый след
              корпоративного действия.
            </div>
          )}
        </div>
      )}

      {needsChoice && (
        <fieldset style={{
          fontSize: 12.5, marginBottom: 8, border: "1px solid var(--line)",
          borderRadius: 6, padding: 8,
        }}>
          <legend style={{ fontSize: 12, color: "var(--amber)" }}>
            Подходящих бумаг несколько: выбор за вами, система не угадывает.
          </legend>
          {suggestions.map((candidate, index) => (
            <label key={`${candidate.from_isin}-${candidate.to_isin}-${index}`}
                   style={{ display: "block", padding: "2px 0" }}>
              <input type="radio" name="suggestion-choice"
                     checked={selectedSuggestion === candidate}
                     onChange={() => chooseSuggestion(candidate)}
                     style={{ marginRight: 6 }} />
              {formatQuantity(candidate.from_quantity)} шт. {candidate.from_isin} →{" "}
              {formatQuantity(candidate.to_quantity)} шт. {candidate.to_isin}
              {candidate.blocked_fully && " · получатель заблокирован целиком"}
            </label>
          ))}
        </fieldset>
      )}

      <label style={{ display: "block", fontSize: 12, marginBottom: 6 }}>
        Что произошло
        <select value={kind} onChange={(event) => changeKind(event.target.value as Kind)}
                style={{ display: "block", marginTop: 3, width: "100%" }}>
          {KINDS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>

      {kind === "CONVERSION" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 6 }}>
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

      {kind === "ADJUSTMENT" && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ display: "flex", gap: 12, marginBottom: 6, fontSize: 12 }}>
            <label>
              <input type="radio" name="adjustment-direction" checked={direction === "CREDIT"}
                     onChange={() => changeDirection("CREDIT")} style={{ marginRight: 4 }} />
              Зачислить бумагу
            </label>
            <label>
              <input type="radio" name="adjustment-direction" checked={direction === "DEBIT"}
                     onChange={() => changeDirection("DEBIT")} style={{ marginRight: 4 }} />
              Списать бумагу
            </label>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {direction === "DEBIT" ? (
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
            ) : (
              <>
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
                <label style={{ fontSize: 12, gridColumn: "1 / -1" }}>
                  Себестоимость всей партии, ₽ — если знаете
                  <input value={costBasis} onChange={(e) => setCostBasis(e.target.value)}
                         placeholder="не знаю"
                         style={{ display: "block", width: "100%" }} />
                  <span style={{ display: "block", fontSize: 11, color: "var(--tx-2)" }}>
                    Пусто — себестоимость останется неизвестной, и по позиции не
                    будет ни средней цены, ни доходности.
                  </span>
                </label>
              </>
            )}
          </div>
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

      {rejecting && (
        <div style={{ color: "var(--amber)", fontSize: 12, marginBottom: 6 }}>
          Отклонение необратимо: эту пару система больше не предложит никогда, а
          отменить отклонённое решение нельзя — отмена рассчитана только на
          подтверждённые. Если сомневаетесь, закройте разбор и вернитесь к нему
          позже.
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" onClick={() => confirm("CONFIRMED")}
                disabled={submit.isPending}>
          {submit.isPending ? "Отправляем…" : "Подтвердить"}
        </button>
        {selectedSuggestion && !rejecting && (
          <button type="button" onClick={() => setRejecting(true)}
                  disabled={submit.isPending}>
            Это не конвертация
          </button>
        )}
        {selectedSuggestion && rejecting && (
          <>
            <button type="button" onClick={() => confirm("REJECTED")}
                    disabled={submit.isPending}>
              Отклонить навсегда
            </button>
            <button type="button" onClick={() => setRejecting(false)}
                    disabled={submit.isPending}>
              Передумал
            </button>
          </>
        )}
        <button type="button" onClick={onDone} disabled={submit.isPending}>
          Отмена
        </button>
      </div>
    </div>
  );
}
