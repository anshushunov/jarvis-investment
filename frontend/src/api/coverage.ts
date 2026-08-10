import { BASE_CURRENCY } from "./format";
import type { Overview } from "./client";

// Почему совокупный капитал посчитан не по всему портфелю. Причин две, и они
// разные настолько, что общая формулировка вводит в заблуждение:
//
// - "prices" — у части бумаг нет котировки. Сколько именно таких, известно
//   точно: positions_total минус valued_positions.
// - "rates"  — нет курсов валют. Тогда у бумаги цена как раз есть, но
//   перевести её в рубли нечем, и в итог не попадает вся валютная часть
//   портфеля разом, включая денежные остатки и золото. Курсы грузит задача
//   планировщика раз в сутки, так что на свежей базе это состояние — норма
//   первых часов, а не редкий сбой.
//
// Различать их обязательно: сообщение "цены есть только для N позиций" при
// пустой таблице курсов называет неверную причину и уводит от починки.
export type CoverageWarning =
  | { kind: "rates"; currencies: string[]; valued: number; total: number }
  | { kind: "prices"; valued: number; total: number };

/** Валюты портфеля, отличные от рублёвой: и по бумагам, и по остаткам.
 *
 * Обе половины нужны. position_currencies отвечает за бумаги и содержит валюту
 * даже той позиции, которую оценить не удалось. by_currency добавляет к ним
 * денежные остатки и золото (XAU) — их в списке валют позиций нет вовсе, а без
 * курса они пропадают из капитала ровно так же. */
export function foreignCurrencies(overview: Overview): string[] {
  const all = new Set([...overview.position_currencies, ...Object.keys(overview.by_currency)]);
  return [...all].filter((currency) => currency !== BASE_CURRENCY).sort();
}

export function coverageWarning(overview: Overview): CoverageWarning | null {
  const { valued_positions: valued, positions_total: total } = overview;
  const currencies = foreignCurrencies(overview);

  // Отсутствие курсов идёт первым: когда их нет, доля неоценённых позиций
  // объясняется именно этим, а не котировками, и называть надо устранимую
  // причину. Рублёвому портфелю курсы не нужны — предупреждать не о чем.
  if (overview.fx_as_of === null && currencies.length > 0) {
    return { kind: "rates", currencies, valued, total };
  }
  if (total > 0 && valued < total) {
    return { kind: "prices", valued, total };
  }
  return null;
}
