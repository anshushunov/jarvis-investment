import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "./Badge";
import { Table, Td, Th } from "./Table";

describe("Table", () => {
  it("держит числовые ячейки табличными и по правому краю", () => {
    // Иначе суммы дёргаются при обновлении котировок: у пропорционального
    // шрифта единица уже восьмёрки, и колонка «прыгает» на каждом тике.
    render(
      <Table>
        <tbody><tr><Td numeric>1 234 ₽</Td></tr></tbody>
      </Table>,
    );

    const cell = screen.getByText("1 234 ₽");
    expect(cell.className).toContain("tabular-nums");
    expect(cell.className).toContain("text-right");
  });

  it("не делает табличным текстовый столбец", () => {
    render(
      <Table>
        <tbody><tr><Td>Сбербанк</Td></tr></tbody>
      </Table>,
    );

    expect(screen.getByText("Сбербанк").className).not.toContain("text-right");
  });

  it("подписывает шапку приглушённым", () => {
    render(
      <Table>
        <thead><tr><Th>Бумага</Th></tr></thead>
      </Table>,
    );

    expect(screen.getByText("Бумага").className).toContain("text-muted");
  });
});

describe("Badge", () => {
  it("различает тревожную метку от обычной", () => {
    render(<Badge tone="danger">нет у брокера</Badge>);
    expect(screen.getByText("нет у брокера").className).toContain("text-red");
  });
});
