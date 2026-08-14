import { describe, expect, it } from "vitest";

import type { InstrumentReturn, Returns } from "../api/client";
import { instrumentsFooter } from "./AnalyticsPage";

// Форма фикстуры — из фактического контракта (backend/app/api/schemas.py).
const instrument = (over: Partial<InstrumentReturn>): InstrumentReturn => ({
  instrument_id: 1, ticker: "SBER", name: "Сбербанк", xirr: "0.1000",
  profit: "10000.0000", value: "70000.0000", closed: false, unrealized: null,
  fx_part: null, reason: null, ...over,
});

const base: Returns = {
  period: { from: "2020-07-16", to: "2026-08-13", annualized: true },
  portfolio: {
    xirr: "0.1842", twr: "0.1531", profit: "13900.0000", invested: "100000.0000",
    value: "113900.0000", chain_days: 444, reason: null,
  },
  coverage: {
    days_total: 2219, days_valued: 448, positions_total: 59, positions_valued: 53,
    unpriced: [], chain_breaks: 0, chain_days: 444, currencies_without_rate: [],
  },
  by_account: [],
  by_asset_class: [{
    asset_class: "cash_and_metals", xirr: null, twr: null, profit: "4400.0000",
    invested: "0.0000", value: "43900.0000", chain_days: null, reason: "cash",
  }],
  by_instrument: [instrument({})],
  unattributed: { profit: "-500.0000", fees: "-500.0000", taxes: "0.0000", other: "0.0000" },
};

describe("instrumentsFooter", () => {
  it("называет причину расхождения словами, а не оставляет невязку", () => {
    // Тождество фазы: бумаги + деньги + «Прочее» = прибыль портфеля. В таблице
    // по бумагам строки «Деньги и металлы» нет — она в разрезе по классам, — и
    // разница обязана объясняться, а не молчать (дизайн, раздел 7).
    const text = instrumentsFooter(base);
    expect(text).toMatch(/Итог по таблице/);
    expect(text).toMatch(/9 500 ₽/);
    expect(text).toMatch(/прибыль портфеля 13 900 ₽/);
    expect(text).toMatch(/Разница 4 400 ₽/);
    expect(text).toMatch(/деньги и металлы 4 400 ₽/);
  });

  it("считает бумаги, у которых прибыль не посчитана, и называет их числом", () => {
    const withUnpriced: Returns = {
      ...base,
      by_instrument: [
        instrument({}),
        instrument({ instrument_id: 2, name: "Гонконг", profit: null, value: null,
                     reason: "no_rate" }),
      ],
    };
    expect(instrumentsFooter(withUnpriced)).toMatch(/1 бумаг, у которых прибыль не посчитана/);
  });

  it("говорит о сходимости прямо, когда сходится до копейки", () => {
    // Слагаемых ровно два — бумаги и «Прочее», денег в портфеле нет вовсе, и
    // тогда итог таблицы обязан совпасть с прибылью портфеля.
    const exact: Returns = {
      ...base,
      portfolio: { ...base.portfolio, profit: "9500.0000" },
      by_asset_class: [],
    };
    expect(instrumentsFooter(exact)).toMatch(/сходится до копейки/);
  });
});
