import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AllocationTarget, PositionRow } from "../api/client";
import { percentToShare, shareToPercent, TargetAllocationForm } from "./TargetAllocationForm";

const targets: AllocationTarget[] = [
  { asset_class: "equity", isin: null, ticker: null, name: null, share: "0.6000",
    updated_at: "2026-09-09T10:00:00Z" },
  { asset_class: null, isin: "RU000A101234", ticker: "OFZ", name: "ОФЗ 26238", share: "0.1000",
    updated_at: "2026-09-09T10:00:00Z" },
];

// Форма фикстуры — из фактического контракта (backend/app/api/schemas.py, PositionOut).
const position = (over: Partial<PositionRow>): PositionRow => ({
  isin: "RU0009029540", ticker: "SBER", name: "Сбербанк", broker: "tbank",
  account: "Инвестиционный (1)", instrument_id: 1, asset_class: "equity", currency: "RUB",
  quantity: "10.00000000", average_price: "100.0000", cost_basis_known: true,
  average_price_currency: "RUB", last_price: "150.0000", market_value: "1500.0000",
  profit: "500.0000", profit_percent: "50.0000", value_base: "1500.0000", price_source: "moex",
  blocked: "0.00000000", restricted: false, ...over,
});

const positions = [
  position({}),
  position({ isin: "RU000A101234", ticker: "OFZ", name: "ОФЗ 26238", instrument_id: 2, asset_class: "bonds" }),
];

function renderForm(over: Partial<Parameters<typeof TargetAllocationForm>[0]> = {}) {
  const onSave = vi.fn();
  render(
    <TargetAllocationForm targets={targets} positions={positions} onSave={onSave}
                          saving={false} error={null} {...over} />,
  );
  return onSave;
}

describe("TargetAllocationForm", () => {
  it("переводит долю в проценты и обратно без потери сотых", () => {
    expect(shareToPercent("0.6000")).toBe("60");
    expect(percentToShare("12,5")).toBe("0.1250");
  });

  it("показывает цели процентами и считает остаток «не задано»", () => {
    renderForm();
    expect(screen.getByLabelText("Доля Акции")).toHaveValue("60");
    expect(screen.getByText(/Итого 70 % · не задано 30 %/)).toBeInTheDocument();
  });

  it("не даёт сохранить сумму больше ста", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.clear(screen.getByLabelText("Доля Акции"));
    await user.type(screen.getByLabelText("Доля Акции"), "95");
    expect(screen.getByText(/больше 100 %, сохранить нельзя/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  });

  it("добавляет цель на класс и отправляет доли дробями", async () => {
    const user = userEvent.setup();
    const onSave = renderForm();
    await user.selectOptions(screen.getByLabelText("Класс"), "bonds");
    await user.click(screen.getByRole("button", { name: "Добавить" }));
    await user.type(screen.getByLabelText("Доля Облигации"), "20");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledWith([
      { asset_class: "equity", isin: null, share: "0.6000" },
      { asset_class: null, isin: "RU000A101234", share: "0.1000" },
      { asset_class: "bonds", isin: null, share: "0.2000" },
    ]);
  });

  it("предлагает в бумаги только открытые позиции, ещё не названные целью", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.selectOptions(screen.getByLabelText("Добавить цель"), "instrument");
    const options = screen.getAllByRole("option").map((option) => option.textContent);
    expect(options).toContain("Сбербанк");
    expect(options).not.toContain("ОФЗ 26238");
  });

  it("показывает отказ бэкенда словами", () => {
    renderForm({ error: "У класса «equity» уже задана цель" });
    expect(screen.getByRole("alert")).toHaveTextContent("уже задана цель");
  });
});
