import { describe, expect, it } from "vitest";
import { formatDate, formatMoney, formatPercent, formatQuantity } from "./format";

describe("formatMoney", () => {
  it("группирует разряды неразрывными пробелами и добавляет рубль", () => {
    expect(formatMoney("4812300.0000")).toBe("4 812 300 ₽");
  });

  it("сохраняет копейки для мелких сумм", () => {
    expect(formatMoney("142.5000")).toBe("142,50 ₽");
  });

  it("не теряет точность на больших числах", () => {
    expect(formatMoney("123456789.1200")).toBe("123 456 789 ₽");
  });

  it("показывает прочерк вместо отсутствующего значения", () => {
    expect(formatMoney(null)).toBe("—");
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
