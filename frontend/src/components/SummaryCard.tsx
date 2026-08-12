import { BASE_CURRENCY, formatMoney, isPositiveAmount } from "../api/format";
import { useAnimatedNumber } from "../design/animation";
import { Card, CardTitle } from "../ui/Card";
import { CoverageNotice } from "./CoverageNotice";
import { MoneyValue } from "./MoneyValue";
import type { Overview } from "../api/client";

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

// Капитал приходит строкой и строкой же форматируется — число здесь живёт
// только внутри анимации. Четыре знака после точки сохраняются, чтобы
// formatMoney получил ровно то же значение, что и без анимации.
function AnimatedTotal({ amount }: { amount: string }) {
  const value = useAnimatedNumber(Number.parseFloat(amount));
  return <MoneyValue amount={value.toFixed(4)} currency={BASE_CURRENCY} />;
}

// Синхронизация ушла отсюда на экран «Сделки и расхождения»: она про движение
// данных, а не про их итог, и её место рядом с расхождениями, которые она
// порождает. Сводка отвечает на один вопрос — сколько у меня.
export function SummaryCard({ overview }: { overview: Overview }) {
  return (
    <Card>
      <CardTitle>Совокупный капитал</CardTitle>
      {/* Отступ до цифры задаёт сам CardTitle (8px). Прежний инлайн отбивал
          6px — двухпиксельная разница здесь и есть цена одинаковой подписи у
          всех карточек. */}
      <div className="text-hero font-[650] tracking-[-0.025em]">
        <AnimatedTotal amount={overview.total_value} />
      </div>
      <CapitalParts overview={overview} />
      <RestrictedNotice overview={overview} />
      <CoverageNotice overview={overview} />
    </Card>
  );
}
