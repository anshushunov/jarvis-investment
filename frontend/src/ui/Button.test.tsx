import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("зовёт обработчик по нажатию", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Подтвердить</Button>);

    await userEvent.click(screen.getByRole("button", { name: "Подтвердить" }));

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("не зовёт обработчик, пока отключена", async () => {
    // Отправка решения идёт секунды; повторное нажатие завело бы второе.
    const onClick = vi.fn();
    render(<Button onClick={onClick} disabled>Отправляем…</Button>);

    await userEvent.click(screen.getByRole("button", { name: "Отправляем…" }));

    expect(onClick).not.toHaveBeenCalled();
  });

  it("различает опасное действие видом", () => {
    // «Отклонить навсегда» необратимо, и выглядеть как «Передумал» не должно.
    render(<Button variant="danger">Отклонить навсегда</Button>);
    expect(screen.getByRole("button").className).toContain("text-red");
  });

  it("по умолчанию не отправляет форму", () => {
    // Кнопки живут внутри панели решений рядом с полями; type="submit" по
    // умолчанию отправлял бы форму при нажатии Enter в любом поле.
    render(<Button>Отмена</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });
});
