import { describe, expect, it } from "vitest";
import { coverageWarning, foreignCurrencies } from "./coverage";
import type { Overview } from "./client";

function overview(fields: Partial<Overview> = {}): Overview {
  return {
    total_value: "1000.0000",
    securities_value: "1000.0000",
    cash_value: "0.0000",
    restricted_value: "0.0000",
    by_asset_class: {},
    by_account: {},
    by_currency: { RUB: "1000.0000" },
    position_currencies: ["RUB"],
    as_of: "2026-08-10",
    fx_as_of: "2026-08-10",
    valued_positions: 10,
    positions_total: 10,
    ...fields,
  };
}

describe("coverageWarning", () => {
  it("молчит, когда посчитан весь портфель", () => {
    expect(coverageWarning(overview())).toBeNull();
  });

  it("называет нехватку котировок, когда курсы на месте", () => {
    expect(coverageWarning(overview({ valued_positions: 7 }))).toEqual({
      kind: "prices", valued: 7, total: 10,
    });
  });

  it("называет нехватку курсов, а не котировок", () => {
    // Ровно то состояние, в котором оказывается свежая база: цены уже есть,
    // курсы ЦБ подтянутся только в 12:10 МСК, и до этого валютная часть
    // капитала не считается вовсе. Сообщение про «цены есть только для N
    // позиций» тут называет неверную причину.
    const warning = coverageWarning(overview({
      fx_as_of: null,
      valued_positions: 4,
      position_currencies: ["RUB", "USD", "HKD"],
      by_currency: { RUB: "1000.0000", USD: "500.0000", XAU: "10.00000000" },
    }));

    expect(warning).toEqual({
      kind: "rates", currencies: ["HKD", "USD", "XAU"], valued: 4, total: 10,
    });
  });

  it("не жалуется на курсы рублёвому портфелю", () => {
    // Курсы такому портфелю не нужны, и пустая таблица курсов на его итог не
    // влияет — предупреждать не о чем.
    expect(coverageWarning(overview({ fx_as_of: null }))).toBeNull();
  });

  it("считает валютную часть непосчитанной и тогда, когда все позиции оценены", () => {
    // Позиций в иностранной валюте может не быть вовсе, а денежный остаток и
    // золото — быть. Без курса они выпадают из капитала так же молча.
    expect(coverageWarning(overview({
      fx_as_of: null,
      by_currency: { RUB: "1000.0000", XAU: "10.00000000" },
    }))).toEqual({ kind: "rates", currencies: ["XAU"], valued: 10, total: 10 });
  });
});

describe("foreignCurrencies", () => {
  it("сводит валюты бумаг и остатков, отбрасывая рубль", () => {
    expect(foreignCurrencies(overview({
      position_currencies: ["RUB", "USD"],
      by_currency: { RUB: "1", USD: "2", CNY: "3" },
    }))).toEqual(["CNY", "USD"]);
  });

  it("не теряет валюту позиции, которую не удалось оценить", () => {
    // Неоценённая позиция в by_currency не попадает вовсе, но валютой обладает
    // — и именно про неё предупреждение.
    expect(foreignCurrencies(overview({
      position_currencies: ["RUB", "HKD"],
      by_currency: { RUB: "1" },
    }))).toEqual(["HKD"]);
  });
});
