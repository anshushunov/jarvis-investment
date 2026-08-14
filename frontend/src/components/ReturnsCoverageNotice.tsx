import { Card, CardTitle } from "../ui/Card";
import type { ReturnsCoverage } from "../api/client";

/**
 * Покрытие данных под таблицами разрезов доходности.
 *
 * Не то же самое, что `CoverageNotice`: тот специфичен под форму `Overview`
 * (покрытие оценкой позиций портфеля прямо сейчас — одна дата, currencies
 * без курса), а `ReturnsCoverage` — про качество ИСТОРИИ за период: на
 * скольких днях оценка была полна, сколько раз рвалась цепочка TWR, и
 * отдельно — покрытие позиций на конец периода. Смешивать их в один
 * компонент значило бы либо тащить в `CoverageNotice` поля, которых `Overview`
 * не знает, либо звать чужой примитив на данные, которым он не подходит по
 * форме (см. находки задачи 10).
 */
export function ReturnsCoverageNotice({ coverage }: { coverage: ReturnsCoverage }) {
  const {
    days_total: daysTotal, days_valued: daysValued, chain_breaks: chainBreaks,
    positions_total: positionsTotal, positions_valued: positionsValued,
    unpriced, currencies_without_rate: currenciesWithoutRate,
  } = coverage;

  return (
    <Card>
      <CardTitle>Покрытие данных за период</CardTitle>
      <div className="text-sm text-muted">
        Полная оценка есть на {daysValued} датах из {daysTotal}.
        {chainBreaks > 0 && (
          <>
            {" "}Цепочка TWR разорвана {chainBreaks} раз — в эти дни доходность
            держится на месте, а не измеряется.
          </>
        )}
      </div>

      <div className="mt-1 text-sm text-muted">
        {positionsTotal === null || positionsValued === null
          // Снимки старше фазы 2c своё покрытие позиций не считали — это не
          // то же самое, что «позиций нет», и молчать об этом нельзя.
          ? "Покрытие позиций на конец периода не считалось: снимок старше фазы 2c."
          : `Позиции на конец периода оценены ${positionsValued} из ${positionsTotal}.`}
      </div>

      {unpriced.length > 0 && (
        <div className="mt-1 text-sm text-muted">Без цены: {unpriced.join(", ")}.</div>
      )}

      {currenciesWithoutRate.length > 0 && (
        <div className="mt-1 text-sm text-amber">
          Нет курса к рублю: {currenciesWithoutRate.join(", ")}. Потоки в этих валютах в расчёт не вошли.
        </div>
      )}
    </Card>
  );
}
