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
  if (percent === null) return <span className="text-muted">—</span>;

  const value = Number.parseFloat(percent);
  // Цвет и стрелка вместе: цвет в одиночку ничего не сообщает тому, кто его
  // не различает.
  const tone = value > 0 ? "text-green" : value < 0 ? "text-red" : "text-muted";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "•";
  return (
    <span className={tone}>
      {arrow} {formatPercent(percent)}
    </span>
  );
}
