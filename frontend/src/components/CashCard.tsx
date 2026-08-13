import { formatMoney, formatQuantity } from "../api/format";
import { Card, CardTitle } from "../ui/Card";
import { CardState } from "../ui/CardState";
import type { CashRow } from "../api/client";

// Металлы приходят от брокера валютными кодами: XAU — золото в граммах.
// Подписывать их знаком валюты нельзя, у граммов его нет.
const METAL_LABEL: Record<string, string> = {
  XAU: "золото, г",
  XAG: "серебро, г",
  XPT: "платина, г",
  XPD: "палладий, г",
};

// Заблокированная часть остатка — та же причина недоступности, что и замок у
// позиций в PositionsTable, только для денег. Значок тот же (согласованный
// язык по всему интерфейсу), а не отдельная строка: она бы держала место на
// каждом счету, даже когда блокировки нет, а у владельца сейчас она нулевая
// везде. Молчим, пока заблокированного нет — ноль это не новость.
function BlockedMark({ blocked, currency }: { blocked: string; currency: string }) {
  const blockedQuantity = Number.parseFloat(blocked);
  if (blockedQuantity === 0) return null;

  const amount = METAL_LABEL[currency] ? `${formatQuantity(blocked)} г` : formatMoney(blocked, currency);
  return (
    <span title={`Заблокировано брокером: ${amount}`} className="ml-1 text-amber">
      🔒
    </span>
  );
}

export function CashCard({ rows, error, loading }: {
  rows: CashRow[];
  error: string | null;
  loading: boolean;
}) {
  if (error) return <CardState kind="error">{error}</CardState>;

  // Идущий запрос — не то же самое, что «остатков нет»: без этого признака
  // заглушка про синхронизацию успевала мелькнуть, пока ответ ещё не пришёл,
  // хотя остатки на счетах есть и вот-вот приедут (тот же класс лжи, что уже
  // чинили для PositionsTable и ValueChart на этой странице).
  if (loading) return <CardState kind="loading">Загрузка остатков…</CardState>;

  if (rows.length === 0) {
    return (
      <Card>
        <CardTitle>Денежные остатки</CardTitle>
        <div className="text-sm text-muted">Остатков нет. Они появятся после синхронизации.</div>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Денежные остатки</CardTitle>
      <div className="grid gap-1.5">
        {rows.map((row) => (
          <div
            key={`${row.account}-${row.currency}`}
            // gap, а не только justify-between: в узкой колонке длинное имя
            // счёта вплотную прижимало к себе сумму.
            className="flex justify-between gap-2 text-sm"
          >
            <span className="text-muted">
              {row.account}
              {METAL_LABEL[row.currency] ? ` · ${METAL_LABEL[row.currency]}` : ""}
            </span>
            <span className="tabular-nums">
              {METAL_LABEL[row.currency] ? formatQuantity(row.amount) : formatMoney(row.amount, row.currency)}
              <BlockedMark blocked={row.blocked} currency={row.currency} />
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
