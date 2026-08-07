import { formatMoney, formatPercent } from "../api/format";

export function MoneyValue({ amount, className = "" }: { amount: string | null; className?: string }) {
  return <span className={className}>{formatMoney(amount)}</span>;
}

export function ChangeValue({ percent }: { percent: string }) {
  const value = Number.parseFloat(percent);
  const color = value > 0 ? "var(--green)" : value < 0 ? "var(--red)" : "var(--tx-2)";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "•";
  return (
    <span style={{ color }}>
      {arrow} {formatPercent(percent)}
    </span>
  );
}
