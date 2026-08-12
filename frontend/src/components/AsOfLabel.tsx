import { formatDate } from "../api/format";

/**
 * Возраст данных: когда последний раз обновлялись котировки и курсы.
 *
 * Две даты, а не одна: котировки обновляются каждые пятнадцать минут, курсы —
 * раз в сутки, и общая дата прикрывала бы недельный курс сегодняшней ценой.
 */
export function AsOfLabel({ asOf, fxAsOf }: { asOf: string | null; fxAsOf: string | null }) {
  const priced = formatDate(asOf);
  const rated = formatDate(fxAsOf);

  return (
    <span className="text-xs text-muted">
      {priced ? `данные на ${priced}` : "данные ещё не рассчитаны — нет котировок"}
      {rated ? ` · курсы на ${rated}` : ""}
    </span>
  );
}
