import { formatDate, fractionToPercent } from "../api/format";
import { Card, CardTitle } from "../ui/Card";
import { ChangeValue } from "./MoneyValue";
import type { Returns } from "../api/client";

// Причина отсутствия ставки — словами владельца, а не кодом (см.
// app/returns/metrics.py: REASON_*). Пустая ячейка без объяснения оставляет
// вопрос, на который система знает ответ.
const REASONS: Record<string, string> = {
  no_flows: "Пополнений и изъятий за период не было — доходность вложений посчитать не из чего.",
  no_solution: "Потоков недостаточно для расчёта: все одного знака или в один день.",
  no_full_days: "Ни один день периода не оценён полностью — не хватает цен.",
  series_gaps: "В истории стоимости есть разрывы — сравнивать не с чем.",
  no_history: "История стоимости за период не заполнена.",
  cash: "У денежного остатка доходности нет: проценты на него приходят отдельными записями.",
};

// Доходности две, и каждая подписана вопросом, на который отвечает. Термины
// «XIRR» и «TWR» стоят рядом мелко: они нужны, чтобы сверить с брокером, но
// сами по себе не объясняют ничего.
function Rate({ title, term, question, value, footnote }: {
  title: string;
  term: string;
  question: string;
  value: string | null;
  // Только у TWR: сколько дней цепочка реально измерила. Без этой подписи
  // годовая ставка, посчитанная на куске истории, выглядит посчитанной на
  // всей — живой замер 14.08.2026 дал 444 из 2219 дней.
  footnote?: string;
}) {
  // Знак — стрелкой и цветом одновременно, тем же компонентом, что уже несёт
  // это правило в таблице позиций (MoneyValue.tsx:ChangeValue): цвет в
  // одиночку ничего не сообщает тому, кто его не различает. Доходность —
  // такая же знаковая процентная величина, как profit_percent, второго
  // компонента под неё заводить не нужно. ChangeValue сам форматирует и сам
  // показывает прочерк на null — конверсия доли в проценты (fractionToPercent)
  // здесь единственный шаг, который ему не принадлежит.
  return (
    <div>
      <div className="text-xs text-muted">{title} · {term}</div>
      <div className="text-2xl font-[650] tabular-nums">
        <ChangeValue percent={value === null ? null : fractionToPercent(value)} />
      </div>
      <div className="mt-1 text-xs text-muted">{question}</div>
      {footnote !== undefined && <div className="mt-0.5 text-2xs text-muted">{footnote}</div>}
    </div>
  );
}

export function ReturnsSummary({ returns }: { returns: Returns }) {
  const { period, portfolio, coverage } = returns;

  // null у chain_days значит «TWR для этого периметра не считается вовсе» —
  // подписи измеренного времени тогда тоже не бывает, а не «измерено 0».
  const chainFootnote = portfolio.chain_days === null
    ? undefined
    : `измерено ${portfolio.chain_days} дней из ${coverage.days_total}`;

  return (
    <Card>
      <CardTitle>Доходность</CardTitle>
      <div className="text-xs text-muted">
        {formatDate(period.from)} — {formatDate(period.to)}
        {period.annualized ? "" : " · за период, не в годовых"}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3.5">
        <Rate title="Мои вложения" term="XIRR" value={portfolio.xirr}
              question="сколько принесли мои вложения" />
        <Rate title="Выбор бумаг" term="TWR" value={portfolio.twr}
              question="насколько удачно выбраны бумаги" footnote={chainFootnote} />
      </div>

      {portfolio.reason !== null && (
        <div className="mt-2.5 text-sm text-muted">
          {REASONS[portfolio.reason] ?? portfolio.reason}
        </div>
      )}
    </Card>
  );
}
