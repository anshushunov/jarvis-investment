import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReturnsBreakdown } from "./ReturnsBreakdown";
import type { BreakdownRow } from "./ReturnsBreakdown";

describe("ReturnsBreakdown", () => {
  it("показывает строки разреза с доходностью, прибылью и стоимостью", () => {
    render(<ReturnsBreakdown title="По счетам" rows={[
      { key: "1", title: "Инвестиционный", xirr: "0.1842", profit: "3120455.10",
        value: "10950455.10", reason: null },
    ]} />);
    expect(screen.getByText("Инвестиционный")).toBeInTheDocument();
    expect(screen.getByText(/\+18,4%/)).toBeInTheDocument();
    expect(screen.getByText(/3 120 455 ₽/)).toBeInTheDocument();
    expect(screen.getByText(/10 950 455 ₽/)).toBeInTheDocument();
  });

  it("передаёт знак доходности стрелкой и цветом, а не только текстом", () => {
    // То же правило, что и в ReturnsSummary: цвет в одиночку ничего не
    // сообщает тому, кто его не различает. ChangeValue уже несёт это правило —
    // второй компонент под то же самое заводить нельзя.
    render(<ReturnsBreakdown title="По счетам" rows={[
      { key: "1", title: "Брокерский", xirr: "-0.052", profit: "-45000.00",
        value: "900000.00", reason: null },
    ]} />);
    const mark = screen.getByText(/▼ −5,2%/);
    expect(mark).toHaveClass("text-red");
  });

  it("метит закрытые позиции", () => {
    render(<ReturnsBreakdown title="По бумагам" rows={[
      { key: "1", title: "Обувь России", xirr: null, profit: "-45000.00",
        value: "0.0000", reason: null, closed: true },
    ]} />);
    expect(screen.getByText("закрыта")).toBeInTheDocument();
  });

  it("объясняет причину отсутствия числа словами, а не прочерком без пояснения", () => {
    render(<ReturnsBreakdown title="По бумагам" rows={[
      { key: "1", title: "РусАгро", xirr: null, profit: null,
        value: null, reason: "no_cost_basis" },
    ]} />);
    expect(screen.getByText(/бумага пришла переводом/i)).toBeInTheDocument();
  });

  it("показывает итог и объяснение под таблицей, а не только строки", () => {
    // Сходимость разрезов с целым до сих пор видел только тот, кто запускал
    // прогон в терминале (дизайн, раздел 7: расхождение объясняется, а не
    // остаётся невязкой).
    render(<ReturnsBreakdown title="По бумагам" footer="Итог по таблице 9 500 ₽" rows={[
      { key: "1", title: "Сбербанк", xirr: "0.1", profit: "9500.00",
        value: "70000.00", reason: null },
    ]} />);
    expect(screen.getByText(/Итог по таблице 9 500 ₽/)).toBeInTheDocument();
  });

  it("показывает бумажную прибыль рядом с её валютной частью: доля без своего целого не читается", () => {
    render(<ReturnsBreakdown title="По бумагам" rows={[
      { key: "1", title: "Apple", xirr: "0.21", profit: "26000.00",
        value: "150000.00", reason: null, unrealized: "53555.00", fx_part: "12000.00" },
    ]} />);
    expect(screen.getByText(/бумажная прибыль/i)).toBeInTheDocument();
    expect(screen.getByText("53 555 ₽")).toBeInTheDocument();
  });

  it("показывает валютную часть нереализованной прибыли отдельной колонкой и подписывает, к чему она относится", () => {
    // unrealized/price_part/fx_part раскладывают НЕреализованную прибыль
    // открытых партий, а не profit за период (дизайн, раздел 4.4) — эти числа
    // намеренно разные в фикстуре, чтобы тест ловил путаницу одной с другой.
    render(<ReturnsBreakdown title="По бумагам" rows={[
      { key: "1", title: "Apple", xirr: "0.21", profit: "26000.00",
        value: "150000.00", reason: null, unrealized: "53555.00", fx_part: "12000.00" },
    ]} />);
    expect(screen.getByText(/12 000 ₽/)).toBeInTheDocument();
    // Подпись именно у валютной колонки: рядом стоит вторая, про бумажную
    // прибыль целиком, и «нереализованн» теперь есть у обеих.
    expect(screen.getByText(/нереализованной, не прибыли периода/i)).toBeInTheDocument();
  });

  it("не рисует колонку валютной части там, где её ни у кого нет", () => {
    render(<ReturnsBreakdown title="По счетам" rows={[
      { key: "1", title: "Инвестиционный", xirr: "0.1", profit: "1000.00",
        value: "5000.00", reason: null },
    ]} />);
    expect(screen.queryByText(/из них валютная/i)).not.toBeInTheDocument();
  });

  it("пустой разрез объясняет пустоту, а не показывает голую таблицу", () => {
    render(<ReturnsBreakdown title="По счетам" rows={[]} />);
    expect(screen.getByText(/данных за период нет/i)).toBeInTheDocument();
  });

  it("показывает измеренное время TWR у каждой строки — цепочки разной длины", () => {
    // Живой замер 14.08.2026: счёт 7 и класс bonds измерены на разных кусках
    // истории. Без подписи рядом с каждой строкой оба TWR выглядели бы
    // посчитанными на одном и том же отрезке — а это не так.
    const rows: BreakdownRow[] = [
      { key: "7", title: "Счёт 7", xirr: "0.1", twr: "0.05", chain_days: 251,
        profit: "1000.00", value: "5000.00", reason: null },
      { key: "1", title: "Счёт 1", xirr: "0.2", twr: "0.15", chain_days: 90,
        profit: "2000.00", value: "9000.00", reason: null },
    ];
    render(<ReturnsBreakdown title="По счетам" rows={rows} daysTotal={2219} />);
    expect(screen.getByText(/измерено 251 из 2219 дней/i)).toBeInTheDocument();
    expect(screen.getByText(/измерено 90 из 2219 дней/i)).toBeInTheDocument();
  });

  it("не рисует колонку TWR там, где её не бывает — у разреза по бумагам", () => {
    render(<ReturnsBreakdown title="По бумагам" rows={[
      { key: "1", title: "Сбербанк", xirr: "0.1", profit: "1000.00", value: "5000.00", reason: null },
    ]} />);
    expect(screen.queryByText("TWR")).not.toBeInTheDocument();
  });

  it("подписывает причину «денег и металлов» по-русски словом, а не кодом", () => {
    render(<ReturnsBreakdown title="По классам активов" rows={[
      { key: "cash_and_metals", title: "Деньги и металлы", xirr: null, twr: null,
        chain_days: null, profit: "-16045.00", value: "1200000.00", reason: "cash" },
    ]} />);
    expect(screen.getByText("Деньги и металлы")).toBeInTheDocument();
    expect(screen.getByText(/доходности у денег и металлов нет/i)).toBeInTheDocument();
    // chain_days = null у денежной строки — «измерено» рядом быть не должно,
    // как и у портфельной карточки (см. ReturnsSummary).
    expect(screen.queryByText(/измерено/i)).not.toBeInTheDocument();
  });
});
