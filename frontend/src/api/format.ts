// Бэкенд сериализует Decimal в строку, чтобы не терять точность. Поэтому
// денежные суммы и количества форматируются здесь строковыми операциями и
// никогда не проходят через Number. Единственное исключение в этом модуле —
// formatPercent: процент уже мал, потери не значимы, а результат идёт только
// на экран.

const NBSP = " ";

function group(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

export function formatMoney(raw: string | null | undefined): string {
  if (raw === null || raw === undefined) return "—";
  const [whole, fraction = ""] = raw.split(".");
  const negative = whole.startsWith("-");
  const digits = negative ? whole.slice(1) : whole;
  const kopecks = fraction.slice(0, 2);
  const showKopecks = digits.length <= 4 && kopecks !== "00";
  const body = group(digits) + (showKopecks ? `,${kopecks}` : "");
  return `${negative ? "−" : ""}${body}${NBSP}₽`;
}

export function formatPercent(raw: string | null | undefined): string {
  if (raw === null || raw === undefined) return "—";
  const value = Number.parseFloat(raw);
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(1).replace(".", ",")}%`;
}

export function formatQuantity(raw: string): string {
  const trimmed = raw.replace(/\.?0+$/, "");
  return trimmed.replace(".", ",");
}

// Дата приходит в виде календарной строки "год-месяц-день" без времени —
// разбираем её строковыми операциями, а не через Date, чтобы не словить
// сдвиг суток из-за интерпретации UTC-полуночи в локальном часовом поясе.
export function formatDate(raw: string | null | undefined): string | null {
  if (raw === null || raw === undefined) return null;
  const [year, month, day] = raw.split("-");
  if (!year || !month || !day) return raw;
  return `${day}.${month}.${year}`;
}
