import { BASE_CURRENCY, formatMoney, isPositiveAmount } from "../api/format";
import { Button } from "../ui/Button";
import { Card, CardTitle } from "../ui/Card";
import { CoverageNotice } from "./CoverageNotice";
import { MoneyValue } from "./MoneyValue";
import type { Overview, SyncRunResult } from "../api/client";

const STATUS_LABEL: Record<string, string> = {
  success: "синхронизирован",
  failed: "ошибка синхронизации",
};

// Из чего складывается капитал. Одна общая цифра не отвечает на вопрос,
// изменился портфель или просто пришли деньги на счёт.
function CapitalParts({ overview }: { overview: Overview }) {
  return (
    <div className="mt-2.5 text-xs text-muted">
      Бумаги <span>{formatMoney(overview.securities_value, BASE_CURRENCY)}</span>
      {" · деньги "}
      <span>{formatMoney(overview.cash_value, BASE_CURRENCY)}</span>
    </div>
  );
}

// Недоступное входит в капитал — брокер считает так же. Но распорядиться им
// нельзя, и знать об этом нужно рядом с самой цифрой: у владельца больше
// двадцати таких позиций, это заметная доля портфеля.
function RestrictedNotice({ overview }: { overview: Overview }) {
  // Плашка имеет смысл только у положительной суммы. Ноль сообщать не о чем, а
  // отрицательное «недоступно» достижимо у короткой позиции с блокировкой:
  // обязательство стоит отрицательных денег, и «Недоступно к продаже −1 000 ₽»
  // читалось бы как ошибка расчёта. Сравнение строки с «0.0000» ловило только
  // ноль.
  if (!isPositiveAmount(overview.restricted_value)) return null;

  return (
    <div className="mt-1.5 text-xs text-muted">
      Недоступно к продаже{" "}
      <span className="text-amber">
        {formatMoney(overview.restricted_value, BASE_CURRENCY)}
      </span>
    </div>
  );
}

export function SummaryCard({ overview, onSync, syncing, syncResult, syncErrorMessage }: {
  overview: Overview;
  onSync: () => void;
  syncing: boolean;
  syncResult: SyncRunResult[] | null;
  syncErrorMessage: string | null;
}) {
  return (
    <Card>
      <CardTitle>Совокупный капитал</CardTitle>
      {/* Отступ до цифры задаёт сам CardTitle (8px). Прежний инлайн отбивал
          6px — двухпиксельная разница здесь и есть цена одинаковой подписи у
          всех карточек. */}
      <div className="text-hero font-[650] tracking-[-0.025em]">
        <MoneyValue amount={overview.total_value} currency={BASE_CURRENCY} />
      </div>
      <CapitalParts overview={overview} />
      <RestrictedNotice overview={overview} />
      <CoverageNotice overview={overview} />
      <Button onClick={onSync} disabled={syncing} className="mt-3.5">
        {syncing ? "Синхронизация…" : "Обновить из Т-Банка"}
      </Button>

      {syncErrorMessage && (
        <div className="mt-3 text-sm text-red">{syncErrorMessage}</div>
      )}

      {syncResult && (
        <div className="mt-3.5 grid gap-1.5">
          {syncResult.map((run) => (
            <div key={run.account} className="text-xs">
              <span className={run.status === "success" ? "text-green" : "text-red"}>
                {run.status === "success" ? "✓" : "✕"}
              </span>{" "}
              <span className="text-muted">{run.account}:</span>{" "}
              {STATUS_LABEL[run.status] ?? run.status}
              {run.error && <div className="ml-[18px] text-muted">{run.error}</div>}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
