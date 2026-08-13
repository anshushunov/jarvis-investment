import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardState } from "./CardState";

describe("CardState", () => {
  it("показывает ошибку цветом ошибки", () => {
    render(<CardState kind="error">сеть недоступна</CardState>);
    expect(screen.getByText(/сеть недоступна/).className).toContain("text-red");
  });

  it("не красит ожидание и пустоту как ошибку", () => {
    // Сбой запроса и «данных нет» — разные утверждения о мире. Одинаковый вид
    // заставлял бы владельца гадать, чинить ли сеть или ждать синхронизации.
    render(<CardState kind="loading">Загрузка остатков…</CardState>);
    render(<CardState kind="empty">Остатков нет.</CardState>);

    expect(screen.getByText("Загрузка остатков…").className).not.toContain("text-red");
    expect(screen.getByText("Остатков нет.").className).not.toContain("text-red");
  });

  it("помечает состояние для чтения с экрана", () => {
    // Цвет один не годится: он ничего не сообщает тому, кто его не видит.
    render(<CardState kind="error">сеть недоступна</CardState>);
    expect(screen.getByRole("status")).toHaveTextContent("сеть недоступна");
  });
});
