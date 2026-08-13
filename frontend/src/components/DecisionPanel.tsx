import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type DecisionInput, type ReconciliationRow, type Suggestion } from "../api/client";
import { formatQuantity } from "../api/format";
import { Button } from "../ui/Button";
import { Field, FieldLabel } from "../ui/Field";

// Выпадающий список и многострочное пояснение — не Field (тот про input), но
// выглядеть обязаны так же: до фазы 3 оба рисовались системными элементами
// браузера и выпадали из интерфейса белым пятном.
const CONTROL =
  "block w-full rounded-sm border border-line bg-bg1/60 px-2.5 py-1.5 text-sm text-tx outline-none focus:border-blue";

const KINDS = [
  { value: "CONVERSION", label: "Конвертация: одна бумага стала другой" },
  { value: "ADJUSTMENT", label: "Поправить количество вручную" },
  { value: "ACCEPTED_AS_IS", label: "Принять как есть, расхождение объяснено" },
] as const;

type Kind = (typeof KINDS)[number]["value"];
type Direction = "CREDIT" | "DEBIT";

// Дата события по умолчанию — сегодня по Москве. Конвертация случилась
// когда-то раньше, и владелец обычно знает когда; поле редактируемое именно
// поэтому. Пояс важен: toISOString даёт дату по UTC, и до 03:00 по Москве
// подставлялась бы вчерашняя. Весь остальной проект — снимки, котировки, окно
// истории — живёт по московской календарной дате (backend/app/timeutils.py).
export function moscowToday(): string {
  // en-CA даёт ISO-подобный «ГГГГ-ММ-ДД», который и ждёт <input type="date">.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Moscow",
    year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

// Направление поправки по умолчанию задаёт само расхождение. Прежнее
// безусловное «зачислить» было подсказкой наугад: половина разбираемых строк —
// это бумага, которой у брокера нет, и её надо списывать.
export function defaultDirection(row: ReconciliationRow): Direction {
  if (row.status === "missing_at_broker") return "DEBIT";
  if (row.status === "missing_in_ledger") return "CREDIT";
  // quantity_mismatch: у брокера больше нашего — зачислить, меньше — списать.
  return Number(row.broker_quantity) >= Number(row.ledger_quantity) ? "CREDIT" : "DEBIT";
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
  const [direction, setDirection] = useState<Direction>(defaultDirection(row));
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
  const [effectiveAt, setEffectiveAt] = useState(moscowToday());
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
    <div className="mt-2 rounded-[6px] border border-line p-2.5">
      {certainSuggestion && (
        <div className="mb-2 text-xs">
          Похоже на конвертацию: {formatQuantity(certainSuggestion.from_quantity)} шт.{" "}
          {certainSuggestion.from_isin} → {formatQuantity(certainSuggestion.to_quantity)} шт.{" "}
          {certainSuggestion.to_isin}
          {certainSuggestion.blocked_fully && (
            <div className="text-2xs text-amber">
              Бумага-получатель заблокирована у брокера целиком — частый след
              корпоративного действия.
            </div>
          )}
        </div>
      )}

      {needsChoice && (
        <fieldset className="mb-2 rounded-[6px] border border-line p-2 text-xs">
          <legend className="text-xs text-amber">
            Подходящих бумаг несколько: выбор за вами, система не угадывает.
          </legend>
          {suggestions.map((candidate, index) => (
            <label key={`${candidate.from_isin}-${candidate.to_isin}-${index}`}
                   className="block py-0.5">
              {/* Выбор одного из нескольких — радиогруппа, а не поле ввода:
                  Field к ней не применяется. */}
              <input type="radio" name="suggestion-choice"
                     checked={selectedSuggestion === candidate}
                     onChange={() => chooseSuggestion(candidate)}
                     className="mr-1.5" />
              {formatQuantity(candidate.from_quantity)} шт. {candidate.from_isin} →{" "}
              {formatQuantity(candidate.to_quantity)} шт. {candidate.to_isin}
              {candidate.blocked_fully && " · получатель заблокирован целиком"}
            </label>
          ))}
        </fieldset>
      )}

      <FieldLabel className="mb-1.5 block">
        Что произошло
        <select value={kind} onChange={(event) => changeKind(event.target.value as Kind)}
                className={`mt-[3px] ${CONTROL}`}>
          {KINDS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </FieldLabel>

      {kind === "CONVERSION" && (
        <div className="mb-1.5 grid grid-cols-2 gap-1.5">
          <FieldLabel>
            Из какой бумаги
            <Field value={fromIsin} onChange={(e) => setFromIsin(e.target.value)}
                   className="block w-full" />
          </FieldLabel>
          <FieldLabel>
            Сколько списать
            <Field value={fromQuantity} onChange={(e) => setFromQuantity(e.target.value)}
                   className="block w-full" />
          </FieldLabel>
          <FieldLabel>
            В какую бумагу
            <Field value={toIsin} onChange={(e) => setToIsin(e.target.value)}
                   className="block w-full" />
          </FieldLabel>
          <FieldLabel>
            Сколько зачислить
            <Field value={toQuantity} onChange={(e) => setToQuantity(e.target.value)}
                   className="block w-full" />
          </FieldLabel>
        </div>
      )}

      {kind === "ADJUSTMENT" && (
        <div className="mb-1.5">
          <div className="mb-1.5 flex gap-3 text-xs">
            <label>
              <input type="radio" name="adjustment-direction" checked={direction === "CREDIT"}
                     onChange={() => changeDirection("CREDIT")} className="mr-1" />
              Зачислить бумагу
            </label>
            <label>
              <input type="radio" name="adjustment-direction" checked={direction === "DEBIT"}
                     onChange={() => changeDirection("DEBIT")} className="mr-1" />
              Списать бумагу
            </label>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {direction === "DEBIT" ? (
              <>
                <FieldLabel>
                  Из какой бумаги
                  <Field value={fromIsin} onChange={(e) => setFromIsin(e.target.value)}
                         className="block w-full" />
                </FieldLabel>
                <FieldLabel>
                  Сколько списать
                  <Field value={fromQuantity} onChange={(e) => setFromQuantity(e.target.value)}
                         className="block w-full" />
                </FieldLabel>
              </>
            ) : (
              <>
                <FieldLabel>
                  В какую бумагу
                  <Field value={toIsin} onChange={(e) => setToIsin(e.target.value)}
                         className="block w-full" />
                </FieldLabel>
                <FieldLabel>
                  Сколько зачислить
                  <Field value={toQuantity} onChange={(e) => setToQuantity(e.target.value)}
                         className="block w-full" />
                </FieldLabel>
                <FieldLabel className="col-span-full">
                  Себестоимость всей партии, в валюте бумаги — если знаете
                  <Field value={costBasis} onChange={(e) => setCostBasis(e.target.value)}
                         placeholder="не знаю"
                         className="block w-full" />
                  <span className="block text-2xs text-muted">
                    Пусто — себестоимость останется неизвестной, и по позиции не
                    будет ни средней цены, ни доходности.
                  </span>
                </FieldLabel>
              </>
            )}
          </div>
        </div>
      )}

      <FieldLabel className="mb-1.5 block">
        Дата события
        <Field type="date" value={effectiveAt}
               onChange={(event) => setEffectiveAt(event.target.value)}
               className="mt-[3px] block" />
      </FieldLabel>

      <FieldLabel className="mb-1.5 block">
        Пояснение
        <textarea value={note} onChange={(event) => setNote(event.target.value)}
                  rows={2} className={`mt-[3px] ${CONTROL}`} />
      </FieldLabel>

      {validation && <div className="mb-1.5 text-xs text-red">{validation}</div>}
      {submit.isError && (
        <div className="mb-1.5 text-xs text-red">
          {(submit.error as Error).message}
        </div>
      )}

      {rejecting && (
        <div className="mb-1.5 text-xs text-amber">
          Отклонение необратимо: эту пару система больше не предложит никогда, а
          отменить отклонённое решение нельзя — отмена рассчитана только на
          подтверждённые. Если сомневаетесь, закройте разбор и вернитесь к нему
          позже.
        </div>
      )}

      <div className="flex gap-2">
        <Button onClick={() => confirm("CONFIRMED")} disabled={submit.isPending}>
          {submit.isPending ? "Отправляем…" : "Подтвердить"}
        </Button>
        {selectedSuggestion && !rejecting && (
          <Button onClick={() => setRejecting(true)} disabled={submit.isPending}>
            Это не конвертация
          </Button>
        )}
        {selectedSuggestion && rejecting && (
          <>
            {/* Необратимое действие обязано отличаться видом от «Передумал»:
                отклонённую пару система больше никогда не предложит. */}
            <Button variant="danger" onClick={() => confirm("REJECTED")}
                    disabled={submit.isPending}>
              Отклонить навсегда
            </Button>
            <Button variant="ghost" onClick={() => setRejecting(false)}
                    disabled={submit.isPending}>
              Передумал
            </Button>
          </>
        )}
        <Button variant="ghost" onClick={onDone} disabled={submit.isPending}>
          Отмена
        </Button>
      </div>
    </div>
  );
}
