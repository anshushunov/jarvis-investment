import { describe, expect, it } from "vitest";
import {
  BASE_CURRENCY,
  currencySign,
  formatDate,
  formatMoney,
  formatPercent,
  formatQuantity,
  isPositiveAmount,
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

describe("formatQuantity", () => {
  it("убирает незначащие нули", () => {
    expect(formatQuantity("35.00000000")).toBe("35");
  });

  it("сохраняет дробные паи", () => {
    expect(formatQuantity("0.50000000")).toBe("0,5");
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
