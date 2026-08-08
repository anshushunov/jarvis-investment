// Бэкенд сериализует Decimal в строку, чтобы не терять точность. Поэтому
// денежные суммы и количества форматируются здесь строковыми операциями и
// никогда не проходят через Number. Единственное исключение в этом модуле —
// formatPercent: процент уже мал, потери не значимы, а результат идёт только
// на экран.

const NBSP = " ";

// Базовая валюта портфеля: в ней считается совокупный капитал и все разбивки
// (см. BASE_CURRENCY в backend/app/analytics/service.py). Позиции в других
// валютах в этот итог не входят и показываются собственными итогами.
export const BASE_CURRENCY = "RUB";

// Знак валюты для тех, что реально встречаются в портфеле. Незнакомый код
// подписывается собой же ("SGD"), а не подменяется рублём: подписать доллары
// рублём хуже, чем показать код валюты.
const CURRENCY_SIGN: Record<string, string> = {
  RUB: "₽",
  USD: "$",
  EUR: "€",
  GBP: "£",
  CNY: "¥",
  HKD: "HK$",
  CHF: "CHF",
  KZT: "₸",
  TRY: "₺",
  AMD: "֏",
  BYN: "Br",
};

export function currencySign(currency: string): string {
  return CURRENCY_SIGN[currency.toUpperCase()] ?? currency.toUpperCase();
}

function group(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

// Валюта — обязательный параметр, а не рубль по умолчанию: четверть портфеля
// номинирована в USD, HKD и CNY, и молчаливый рубль в подписи был враньём.
// Округление до копеек строковыми операциями: значение приходит с бэкенда
// строкой ради точности, и Number по дороге тут не появляется. Усечение
// (просто взять первые два знака) занижало бы каждую сумму — «142,999»
// показывалось как «142,99».
function roundToKopecks(digits: string, fraction: string): [string, string] {
  const kopecks = fraction.slice(0, 2).padEnd(2, "0");
  if ((fraction[2] ?? "0") < "5") return [digits, kopecks];

  const carried = (Number.parseInt(kopecks, 10) + 1).toString().padStart(2, "0");
  if (carried !== "100") return [digits, carried];

  // Копейки переполнились в рубль: прибавляем единицу к целой части — тоже
  // строкой, чтобы не потерять точность на больших суммах.
  return [bumpInteger(digits), "00"];
}

function bumpInteger(digits: string): string {
  const result = digits.split("");
  let index = result.length - 1;
  while (index >= 0) {
    if (result[index] !== "9") {
      result[index] = String(Number(result[index]) + 1);
      return result.join("");
    }
    result[index] = "0";
    index -= 1;
  }
  return `1${result.join("")}`;
}

export function formatMoney(raw: string | null | undefined, currency: string): string {
  if (raw === null || raw === undefined) return "—";
  const [rawWhole, fraction = ""] = raw.split(".");
  const negative = rawWhole.startsWith("-");
  const [digits, kopecks] = roundToKopecks(negative ? rawWhole.slice(1) : rawWhole, fraction);
  const showKopecks = digits.length <= 4 && kopecks !== "00";
  const body = group(digits) + (showKopecks ? `,${kopecks}` : "");
  return `${negative ? "−" : ""}${body}${NBSP}${currencySign(currency)}`;
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
