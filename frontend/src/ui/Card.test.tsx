import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Card, CardTitle } from "./Card";

describe("Card", () => {
  it("рисует содержимое на подложке", () => {
    render(<Card>содержимое</Card>);
    expect(screen.getByText("содержимое")).toBeInTheDocument();
  });

  it("принимает дополнительные классы, не теряя своих", () => {
    // Карточке иногда нужен свой отступ или колонка сетки, и способ добавить
    // их не должен требовать второй обёртки вокруг.
    render(<Card className="col-span-2">содержимое</Card>);
    const card = screen.getByText("содержимое");
    expect(card.className).toContain("col-span-2");
    expect(card.className).toContain("rounded-lg");
  });

  it("подписывает карточку приглушённым заголовком", () => {
    render(<CardTitle>Денежные остатки</CardTitle>);
    expect(screen.getByText("Денежные остатки").className).toContain("text-muted");
  });
});
