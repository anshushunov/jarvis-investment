import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AsOfLabel } from "./AsOfLabel";

describe("AsOfLabel", () => {
  it("называет обе даты отдельно", () => {
    // Котировки и курсы обновляются с разной частотой, и одна дата на двоих
    // прикрывала бы недельные курсы сегодняшней ценой.
    render(<AsOfLabel asOf="2026-08-12" fxAsOf="2026-08-08" />);

    expect(screen.getByText(/данные на 12\.08\.2026/)).toBeInTheDocument();
    expect(screen.getByText(/курсы на 08\.08\.2026/)).toBeInTheDocument();
  });

  it("говорит о причине, когда даты нет", () => {
    render(<AsOfLabel asOf={null} fxAsOf={null} />);
    expect(screen.getByText(/нет котировок/)).toBeInTheDocument();
  });

  it("молчит о курсах, когда их не было в расчёте", () => {
    // У чисто рублёвого портфеля курсов в расчёте нет вовсе, и «курсы на —»
    // выглядело бы поломкой.
    render(<AsOfLabel asOf="2026-08-12" fxAsOf={null} />);
    expect(screen.queryByText(/курсы на/)).not.toBeInTheDocument();
  });
});
