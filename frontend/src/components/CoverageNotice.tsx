import { coverageWarning } from "../api/coverage";
import type { Overview } from "../api/client";

/**
 * Охват оценки: какой частью портфеля посчитана главная цифра.
 *
 * Стоит вплотную к сумме и называет настоящую причину: нет котировок и нет
 * курсов — разные поломки, и чинятся они по-разному. Вынесено из SummaryCard:
 * то же предупреждение нужно на экране активов, а из чужого файла его не взять.
 */
export function CoverageNotice({ overview }: { overview: Overview }) {
  const warning = coverageWarning(overview);
  if (warning === null) return null;

  if (warning.kind === "rates") {
    return (
      <div className="mt-2.5 rounded-sm bg-red/[0.14] px-2.5 py-[7px] text-sm text-red">
        Нет курса к рублю: {warning.currencies.join(", ")}. Всё, что в этих валютах, в
        сумму не входит — ни бумаги, ни остатки, ни металлы. Курсы подтянутся сами
        (ЦБ, ежедневно в 12:10 МСК; металлы — с MOEX) или вручную — см. README,
        «Курсы, цены и оценка капитала». В рублях посчитаны {warning.valued} позиций
        из {warning.total}.
      </div>
    );
  }

  return (
    <div className="mt-2.5 rounded-sm bg-amber/[0.14] px-2.5 py-[7px] text-sm text-amber">
      Часть портфеля не оценена: цены есть только для {warning.valued} позиций из{" "}
      {warning.total}. Остальные в эту сумму не входят.
    </div>
  );
}
