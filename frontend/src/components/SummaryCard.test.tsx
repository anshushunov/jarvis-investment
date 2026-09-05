import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SummaryCard } from "./SummaryCard";
import { AnimationProvider } from "../design/animation";
import type { Overview, ReturnMetric } from "../api/client";

// Совокупный капитал анимируется числом (useAnimatedNumber), а хук требует
// AnimationProvider из контекста — тот же, что оборачивает приложение в
// App.tsx. Без него рендер падает до того, как дело доходит до доходности.
function renderCard(props: { overview: Overview; returns: ReturnMetric | null }) {
  return render(
    <AnimationProvider>
      <SummaryCard {...props} />
    </AnimationProvider>,
  );
}

// Форма фикстуры — из фактического контракта (backend/app/api/schemas.py,
// ReturnsOut), а не из устаревшего брифа: chain_days есть у каждой метрики.
const overview: Overview = {
  total_value: "10950455.1000", securities_value: "9950455.1000",
  cash_value: "1000000.0000", restricted_value: "0.0000",
  by_asset_class: {}, by_account: {}, by_currency: {},
  position_currencies: ["RUB"], currencies_without_rate: [],
  as_of: "2026-08-13", fx_as_of: "2026-08-13",
  valued_positions: 59, positions_total: 59,
};

const metric: ReturnMetric = {
  xirr: "0.1842", twr: "0.1531", profit: "3120455.1000",
  invested: "7830000.0000", value: "10950455.1000",
  chain_days: 444, reason: null,
};

describe("SummaryCard", () => {
  it("показывает доходность и прибыль рядом с капиталом", () => {
    renderCard({ overview, returns: metric });
    // Знак — стрелкой и цветом одновременно, тем же ChangeValue, что уже
    // несёт это правило на «Аналитике» (ReturnsSummary.tsx) и в таблице
    // позиций: полный текст узла — "▲ +18,4%", а не голое число.
    const xirr = screen.getByText(/▲ \+18,4%/);
    expect(xirr).toHaveClass("text-green");
    expect(screen.getByText(/3 120 455 ₽/)).toBeInTheDocument();
  });

  it("без доходности карточка остаётся прежней", () => {
    renderCard({ overview, returns: null });
    expect(screen.getByText("Совокупный капитал")).toBeInTheDocument();
    // Пока ответа нет — ни пустого места, ни строки-заглушки: карточка
    // выглядит ровно как до задачи.
    expect(screen.queryByText(/Доходность/)).not.toBeInTheDocument();
  });

  it("без ставки XIRR показывает прочерк, а не ноль", () => {
    renderCard({ overview, returns: { ...metric, xirr: null, reason: "no_flows" } });
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText(/3 120 455 ₽/)).toBeInTheDocument();
  });
});
