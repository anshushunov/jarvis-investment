import { describe, expect, it } from "vitest";
import { coverageWarning } from "./coverage";
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
    currencies_without_rate: [],
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
      currencies_without_rate: ["HKD", "USD", "XAU"],
    }));

    expect(warning).toEqual({
      kind: "rates", currencies: ["HKD", "USD", "XAU"], valued: 4, total: 10,
    });
  });

  it("не жалуется на курсы рублёвому портфелю", () => {
    // Курсы такому портфелю не нужны, и пустая таблица курсов на его итог не
    // влияет — предупреждать не о чем. Пустая дата курсов сама по себе поводом
    // не является: у чисто рублёвого портфеля не было ни одного пересчёта.
    expect(coverageWarning(overview({ fx_as_of: null }))).toBeNull();
  });

  it("предупреждает о единственной выпавшей валюте при остальных курсах на месте", () => {
    // Таблица курсов полна, дата свежая, все позиции оценены — и при этом
    // грамм серебра выпадает из капитала, потому что XAG в ней нет. Пока
    // предупреждение цеплялось за пустую дату курсов, такой остаток исчезал
    // молча: покрытие считает только позиции и об остатках не знает.
    expect(coverageWarning(overview({
      currencies_without_rate: ["XAG"],
    }))).toEqual({ kind: "rates", currencies: ["XAG"], valued: 10, total: 10 });
  });
});
