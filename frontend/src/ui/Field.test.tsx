import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Field, FieldLabel } from "./Field";

describe("Field", () => {
  it("передаёт введённое наружу", async () => {
    const onChange = vi.fn();
    render(<Field aria-label="Количество" value="" onChange={onChange} />);

    await userEvent.type(screen.getByLabelText("Количество"), "7");

    expect(onChange).toHaveBeenCalled();
  });

  it("связывает подпись с полем", () => {
    // Подпись рядом — не то же самое, что подпись, связанная с полем: по
    // несвязанной нельзя попасть в поле щелчком и её не читает экранный диктор.
    render(
      <>
        <FieldLabel htmlFor="quantity">Количество</FieldLabel>
        <Field id="quantity" value="" onChange={() => {}} />
      </>,
    );

    expect(screen.getByLabelText("Количество")).toBeInTheDocument();
  });

  it("держит числа табличными", () => {
    // Количество и цены набираются в поле и должны стоять в тех же колонках,
    // что и в таблице позиций.
    render(<Field aria-label="Цена" value="" onChange={() => {}} />);
    expect(screen.getByLabelText("Цена").className).toContain("tabular-nums");
  });
});
