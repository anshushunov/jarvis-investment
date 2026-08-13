import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Decision, ReconciliationRow } from "../api/client";
import { formatQuantity } from "../api/format";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { DecisionPanel } from "./DecisionPanel";

const TEXT: Record<string, string> = {
  quantity_mismatch: "количество не совпадает",
  missing_in_ledger: "есть у брокера, но нет в журнале",
  missing_at_broker: "есть в журнале, но нет у брокера",
};

// Тон метки — про тяжесть расхождения, а не про его вид: разошедшееся
// количество ещё может оказаться корпоративным действием, а бумага, которой
// нет с одной из сторон, — это либо пропущенная операция, либо чужая позиция.
const TONE = {
  quantity_mismatch: "warning",
  missing_in_ledger: "danger",
  missing_at_broker: "danger",
} as const;

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
    <Card className="border-red/45 bg-red/[0.08]">
      <div className="font-semibold text-red">Не удалось проверить расхождения с брокером</div>
      <div className="mt-1.5 text-sm text-muted">
        {error}. Это не значит, что расхождений нет — сверка сейчас недоступна.
      </div>
    </Card>
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
    <Card className="border-amber/45 bg-amber/[0.08]">
      {/* Заголовок баннера, а не кнопка интерфейса: примитив Button приглушил
          бы его до обычного действия, тогда как это единственная строка,
          которой сверка сообщает о находке. */}
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent p-0 text-left font-semibold text-amber [font:inherit] [font-weight:600]"
      >
        <span aria-hidden="true" className="text-2xs">{expanded ? "▼" : "▶"}</span>
        <span>Расхождения с данными брокера: {rows.length}</span>
        <span className="text-sm font-normal text-muted">
          {expanded ? "скрыть" : "показать"}
        </span>
      </button>

      {expanded && (
        <div className="mt-2">
          {rows.map((row, index) => (
            // Сверка считается по каждому счёту отдельно: один и тот же ISIN может
            // дать две строки на двух разных счетах — ключ обязан учитывать счёт,
            // а строка обязана показывать, о каком счёте речь (тот же класс бага,
            // что был найден и исправлен в таблице позиций).
            <div key={`${row.account}-${row.isin}-${index}`} className="py-[3px] text-sm text-muted">
              {row.account} · {row.isin}:{" "}
              <Badge tone={TONE[row.status as keyof typeof TONE]}>
                {TEXT[row.status] ?? row.status}
              </Badge>{" "}
              — в журнале {formatQuantity(row.ledger_quantity)},
              у брокера {formatQuantity(row.broker_quantity)}
              {" "}
              <button
                type="button"
                onClick={() => setOpen(open === `${row.account}-${row.isin}-${index}` ? null : `${row.account}-${row.isin}-${index}`)}
                className="cursor-pointer border-none bg-transparent p-0 text-amber underline [font:inherit]"
              >
                разобрать
              </button>
              {row.suggestions.length > 0 && (
                <span title="Система нашла подходящую пару" className="ml-1">💡</span>
              )}
              {open === `${row.account}-${row.isin}-${index}` && (
                <DecisionPanel row={row} onDone={() => setOpen(null)} />
              )}
            </div>
          ))}
          <div className="mt-2 text-xs text-muted">
            Позиции не исправлены автоматически: за этим обычно стоят корпоративные действия —
            конвертации расписок, смены ISIN, дробления. Брокер не присылает их отдельной операцией.
          </div>
        </div>
      )}
    </Card>
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
    <Card>
      <div className="mb-1 text-xs text-muted">
        Уже разобрано: {decisions.data.length}
      </div>
      {decisions.data.map((decision) => (
        <div key={decision.id} className="py-0.5 text-xs text-muted">
          {decision.account} · {decision.from_isin ?? "—"} → {decision.to_isin ?? "—"}
          {decision.status === "REVERTED" && " (отменено)"} — {decision.note}
          {isRevertable(decision) && reverting !== decision.id && (
            <>
              {" "}
              <button
                type="button"
                onClick={() => start(decision.id)}
                className="cursor-pointer border-none bg-transparent p-0 text-amber underline [font:inherit]"
              >
                отменить решение №{decision.id}
              </button>
            </>
          )}
          {reverting === decision.id && (
            <div className="mt-1 rounded-[6px] border border-line p-2">
              <label className="block">
                Почему отменяем
                {/* Не Field: тот про однострочный input, а причина отмены —
                    текст в несколько строк. Вид набран теми же классами. */}
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={2}
                  className="mt-[3px] block w-full rounded-sm border border-line bg-bg1/60 px-2.5 py-1.5 text-sm text-tx outline-none focus:border-blue"
                />
              </label>
              {validation && <div className="mt-1 text-red">{validation}</div>}
              {revert.isError && (
                <div className="mt-1 text-red">{(revert.error as Error).message}</div>
              )}
              <div className="mt-1.5 flex gap-2">
                <Button onClick={() => submit(decision.id)} disabled={revert.isPending}>
                  {revert.isPending ? "Отменяем…" : "Отменить"}
                </Button>
                <Button variant="ghost" onClick={() => setReverting(null)} disabled={revert.isPending}>
                  Не отменять
                </Button>
              </div>
            </div>
          )}
        </div>
      ))}
    </Card>
  );
}
