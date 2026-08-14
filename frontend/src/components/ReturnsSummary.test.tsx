import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Returns } from "../api/client";
import { ReturnsSummary } from "./ReturnsSummary";

// Форма фикстуры — из фактического контракта (backend/app/api/schemas.py,
// ReturnsOut), а не из устаревшего брифа: chain_days появился у каждой
// метрики, profit/invested/value портфеля не бывают null (это свойство
// только строк по бумагам — InstrumentReturnOut).
const base: Returns = {
  period: { from: "2020-07-16", to: "2026-08-13", annualized: true },
  portfolio: {
    xirr: "0.1842", twr: "0.1531", profit: "3120455.10", invested: "7830000.00",
    value: "10950455.10", chain_days: 444, reason: null,
  },
  coverage: {
    days_total: 2219, days_valued: 448, positions_total: 59, positions_valued: 53,
    unpriced: ["AGRO"], chain_breaks: 0, chain_days: 444, currencies_without_rate: [],
  },
  by_account: [], by_asset_class: [], by_instrument: [],
  unattributed: { profit: "-103015.00", fees: "-34868.39", taxes: "-77477.00", other: "9330.39" },
};

describe("ReturnsSummary", () => {
  it("показывает обе доходности процентами", () => {
    render(<ReturnsSummary returns={base} />);
    expect(screen.getByText("+18,4%")).toBeInTheDocument();
    expect(screen.getByText("+15,3%")).toBeInTheDocument();
  });

  it("объясняет каждую доходность вопросом, а не термином", () => {
    render(<ReturnsSummary returns={base} />);
    expect(screen.getByText(/сколько принесли мои вложения/i)).toBeInTheDocument();
    expect(screen.getByText(/насколько удачно выбраны бумаги/i)).toBeInTheDocument();
  });

  it("называет причину вместо прочерка", () => {
    const withoutRate: Returns = {
      ...base,
      portfolio: { ...base.portfolio, xirr: null, twr: null, chain_days: null, reason: "no_flows" },
    };
    render(<ReturnsSummary returns={withoutRate} />);
    expect(screen.getByText(/пополнений и изъятий за период не было/i)).toBeInTheDocument();
  });

  it("предупреждает, когда период короче года", () => {
    const short: Returns = {
      ...base,
      period: { from: "2026-01-01", to: "2026-02-14", annualized: false },
    };
    render(<ReturnsSummary returns={short} />);
    expect(screen.getByText(/за период, не в годовых/i)).toBeInTheDocument();
  });

  it("показывает границы периода: цифра посчитана не с начала времён", () => {
    render(<ReturnsSummary returns={base} />);
    expect(screen.getByText(/16\.07\.2020/)).toBeInTheDocument();
  });

  it("показывает измеренное время TWR рядом со ставкой — иначе цифра врёт", () => {
    // Живой замер 14.08.2026: TWR портфеля за всё время измерен на 444 днях
    // из 2219 — без этой подписи -25% выглядели бы посчитанными на всей
    // истории, а не на куске, кончающемся маем 2022 года.
    render(<ReturnsSummary returns={base} />);
    expect(screen.getByText(/измерено 444 дней из 2219/i)).toBeInTheDocument();
  });

  it("не показывает измеренное время, когда TWR для периметра не считается вовсе", () => {
    const noChain: Returns = {
      ...base,
      portfolio: { ...base.portfolio, twr: null, chain_days: null, reason: "cash" },
    };
    render(<ReturnsSummary returns={noChain} />);
    expect(screen.queryByText(/измерено/i)).not.toBeInTheDocument();
  });

  it("показывает ноль измеренных дней, а не прячет его", () => {
    // 0 — цепочка построена, но не измерила ни одного шага. Это не то же
    // самое, что «не считается вовсе» (null), и подменять одно другим нельзя.
    const zeroChain: Returns = {
      ...base,
      portfolio: { ...base.portfolio, twr: null, chain_days: 0, reason: "no_full_days" },
      coverage: { ...base.coverage, chain_days: 0 },
    };
    render(<ReturnsSummary returns={zeroChain} />);
    expect(screen.getByText(/измерено 0 дней из 2219/i)).toBeInTheDocument();
  });
});
