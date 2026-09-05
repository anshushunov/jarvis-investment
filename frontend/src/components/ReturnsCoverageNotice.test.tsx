import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReturnsCoverageNotice } from "./ReturnsCoverageNotice";
import type { ReturnsCoverage } from "../api/client";

const base: ReturnsCoverage = {
  days_total: 2219, days_valued: 448, positions_total: 59, positions_valued: 53,
  unpriced: [], chain_breaks: 0, chain_days: 444, currencies_without_rate: [],
};

describe("ReturnsCoverageNotice", () => {
  it("показывает, на скольких датах оценка полна", () => {
    render(<ReturnsCoverageNotice coverage={base} />);
    expect(screen.getByText(/448 датах из 2219/)).toBeInTheDocument();
  });

  it("называет разрывы цепочки TWR, а не прячет их", () => {
    render(<ReturnsCoverageNotice coverage={{ ...base, chain_breaks: 7 }} />);
    expect(screen.getByText(/разорвана 7 раз/i)).toBeInTheDocument();
  });

  it("не пишет про разрывы, когда их нет", () => {
    render(<ReturnsCoverageNotice coverage={base} />);
    expect(screen.queryByText(/разорвана/i)).not.toBeInTheDocument();
  });

  it("называет бумаги без цены поимённо", () => {
    render(<ReturnsCoverageNotice coverage={{ ...base, unpriced: ["AGRO", "FIVE"] }} />);
    expect(screen.getByText(/AGRO, FIVE/)).toBeInTheDocument();
  });

  it("предупреждает про валюты без курса", () => {
    render(<ReturnsCoverageNotice coverage={{ ...base, currencies_without_rate: ["HKD"] }} />);
    expect(screen.getByText(/HKD/)).toBeInTheDocument();
    expect(screen.getByText(/нет курса/i)).toBeInTheDocument();
  });

  it("объясняет неизвестное покрытие позиций словами, а не молчит о нём", () => {
    // null — покрытие позиций на конец периода никто не считал (снимки старше
    // фазы 2c), это не то же самое, что «ноль позиций».
    render(<ReturnsCoverageNotice coverage={{ ...base, positions_total: null, positions_valued: null }} />);
    expect(screen.getByText(/не считалось/i)).toBeInTheDocument();
  });
});
