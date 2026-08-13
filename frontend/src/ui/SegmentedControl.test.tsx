import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SegmentedControl } from "./SegmentedControl";

const OPTIONS = [
  { value: 30, label: "Месяц" },
  { value: 365, label: "Год" },
  { value: 0, label: "Всё время" },
];

describe("SegmentedControl", () => {
  it("сообщает выбранное значение", async () => {
    const onChange = vi.fn();
    render(<SegmentedControl options={OPTIONS} value={365} onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: "Месяц" }));

    expect(onChange).toHaveBeenCalledWith(30);
  });

  it("помечает текущий выбор для чтения с экрана", () => {
    render(<SegmentedControl options={OPTIONS} value={365} onChange={() => {}} />);
    expect(screen.getByRole("radio", { name: "Год" })).toBeChecked();
  });
});
