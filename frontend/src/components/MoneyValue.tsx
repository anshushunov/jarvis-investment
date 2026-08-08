import { formatMoney, formatPercent } from "../api/format";

export function MoneyValue({ amount, currency, className = "" }: {
  amount: string | null;
  // Валюта обязательна: подписывать рублём то, что номинировано в USD или
  // HKD, — враньё, которое с экрана никак не отличить от правды.
  currency: string;
  className?: string;
}) {
  return <span className={className}>{formatMoney(amount, currency)}</span>;
}

export function ChangeValue({ percent }: { percent: string | null }) {
  // Оценки нет — показываем прочерк, а не «• 0,0%»: нулевой результат и
  // отсутствие результата это разные вещи.
  if (percent === null) return <span style={{ color: "var(--tx-2)" }}>—</span>;

  const value = Number.parseFloat(percent);
  const color = value > 0 ? "var(--green)" : value < 0 ? "var(--red)" : "var(--tx-2)";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "•";
  return (
    <span style={{ color }}>
      {arrow} {formatPercent(percent)}
    </span>
  );
}
