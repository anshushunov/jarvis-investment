import { describe, expect, it } from "vitest";
import {
  ASSET_CLASS_TITLES,
  BASE_CURRENCY,
  currencySign,
  formatDate,
  formatMoney,
  formatPercent,
  formatQuantity,
  isPositiveAmount,
  isZeroAmount,
  subtractMoney,
  sumMoney,
} from "./format";

describe("isPositiveAmount", () => {
  it("отличает ноль и отрицательное от положительного", () => {
    // Отрицательное «недоступно к продаже» достижимо: короткая позиция с
    // блокировкой стоит отрицательных денег (см. test_analytics.py,
    // test_blocked_short_position_does_not_flip_the_sign). Плашке о нём
    // сообщать нечего — как и о нуле.
    expect(isPositiveAmount("0.0000")).toBe(false);
    expect(isPositiveAmount("-0.0000")).toBe(false);
    expect(isPositiveAmount("-1000.0000")).toBe(false);
    expect(isPositiveAmount("782.2700")).toBe(true);
    expect(isPositiveAmount("0.0001")).toBe(true);
  });
});

describe("formatMoney", () => {
  it("группирует разряды неразрывными пробелами и добавляет рубль", () => {
    expect(formatMoney("4812300.0000", BASE_CURRENCY)).toBe("4 812 300 ₽");
  });

  it("сохраняет копейки для мелких сумм", () => {
    expect(formatMoney("142.5000", BASE_CURRENCY)).toBe("142,50 ₽");
  });

  it("не теряет точность на больших числах", () => {
    expect(formatMoney("123456789.1200", BASE_CURRENCY)).toBe("123 456 789 ₽");
  });

  it("показывает прочерк вместо отсутствующего значения", () => {
    expect(formatMoney(null, BASE_CURRENCY)).toBe("—");
  });

  it("подписывает сумму её собственной валютой, а не рублём", () => {
    expect(formatMoney("142.5000", "USD")).toBe("142,50 $");
    expect(formatMoney("1200.0000", "HKD")).toBe("1 200 HK$");
    expect(formatMoney("980.0000", "CNY")).toBe("980 ¥");
  });

  it("незнакомую валюту подписывает её кодом, а не подменяет рублём", () => {
    expect(formatMoney("500.0000", "SGD")).toBe("500 SGD");
    expect(currencySign("sgd")).toBe("SGD");
  });

  it("округляет копейки, а не усекает их", () => {
    expect(formatMoney("142.5060", BASE_CURRENCY)).toBe("142,51 ₽");
    expect(formatMoney("142.5040", BASE_CURRENCY)).toBe("142,50 ₽");
    expect(formatMoney("-142.5060", BASE_CURRENCY)).toBe("−142,51 ₽");
  });

  it("переносит переполнение копеек в рубли", () => {
    expect(formatMoney("142.9990", BASE_CURRENCY)).toBe("143 ₽");
    expect(formatMoney("999.9990", BASE_CURRENCY)).toBe("1 000 ₽");
    expect(formatMoney("9.9990", BASE_CURRENCY)).toBe("10 ₽");
  });

  it("округляет рубли и у крупных сумм, где копейки не показываются", () => {
    // Скрыть копейки ради читаемости — можно, отбросить их — нет: иначе от
    // этого порога и выше каждая сумма занижается.
    expect(formatMoney("10000.9900", BASE_CURRENCY)).toBe("10 001 ₽");
    expect(formatMoney("10000.5000", BASE_CURRENCY)).toBe("10 001 ₽");
    expect(formatMoney("10000.4900", BASE_CURRENCY)).toBe("10 000 ₽");
    expect(formatMoney("99999.9900", BASE_CURRENCY)).toBe("100 000 ₽");
    expect(formatMoney("-10000.9900", BASE_CURRENCY)).toBe("−10 001 ₽");
  });
});

describe("formatPercent", () => {
  it("добавляет знак для роста", () => {
    expect(formatPercent("50.0000")).toBe("+50,0%");
  });

  it("оставляет минус для падения", () => {
    expect(formatPercent("-3.2500")).toBe("−3,3%");
  });
});

describe("sumMoney", () => {
  it("складывает деньги без Number: копейки не теряются", () => {
    // Через float 0.1 + 0.2 даёт 0.30000000000000004, и итог под таблицей из
    // 253 строк разъезжается с бэкендом. Здесь складываются целые доли.
    expect(sumMoney(["0.1000", "0.2000"])).toBe("0.3000");
    expect(sumMoney(["3120455.1000", "-103015.5000"])).toBe("3017439.6000");
  });

  it("пропускает неизвестные значения, а не считает их нулём", () => {
    // У бумаги без цены прибыль неизвестна: ноль утверждал бы, что она не
    // принесла ничего.
    expect(sumMoney(["1000.0000", null, undefined])).toBe("1000.0000");
  });

  it("складывает пустой список в ноль", () => {
    expect(sumMoney([])).toBe("0.0000");
  });
});

describe("subtractMoney", () => {
  it("вычитает и сохраняет знак", () => {
    expect(subtractMoney("100.0000", "130.5000")).toBe("-30.5000");
    expect(subtractMoney("-0.0100", "-0.0200")).toBe("0.0100");
  });
});

describe("isZeroAmount", () => {
  it("считает нулём и «0.0000», и «-0.0000»", () => {
    expect(isZeroAmount("0.0000")).toBe(true);
    expect(isZeroAmount("-0.0000")).toBe(true);
    expect(isZeroAmount("-0.0100")).toBe(false);
  });
});

describe("formatQuantity", () => {
  it("убирает незначащие нули", () => {
    expect(formatQuantity("35.00000000")).toBe("35");
  });

  it("сохраняет дробные паи", () => {
    expect(formatQuantity("0.50000000")).toBe("0,5");
  });
});

describe("ASSET_CLASS_TITLES", () => {
  it("подписывает известные классы по-русски", () => {
    expect(ASSET_CLASS_TITLES.equity).toBe("Акции");
    expect(ASSET_CLASS_TITLES.bonds).toBe("Облигации");
  });

  it("подписывает деньги и металлы разреза доходности одной строкой", () => {
    // cash_and_metals — ключ, которого не бывает в Overview.by_asset_class
    // (там классы денег и металлов раздельные): он приходит только из разреза
    // доходности, где деньги и металлы посчитаны одним периметром (см.
    // MONEY_ROW_CLASS в backend/app/returns/breakdown.py).
    expect(ASSET_CLASS_TITLES.cash_and_metals).toBe("Деньги и металлы");
  });
});

describe("formatDate", () => {
  it("переводит календарную дату в формат ДД.ММ.ГГГГ", () => {
    expect(formatDate("2026-08-07")).toBe("07.08.2026");
  });

  it("возвращает null вместо отсутствующей даты", () => {
    expect(formatDate(null)).toBeNull();
    expect(formatDate(undefined)).toBeNull();
  });
});
