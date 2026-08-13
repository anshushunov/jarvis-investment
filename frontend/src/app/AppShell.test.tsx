import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";
import { NAV_ITEMS } from "./routes";

function renderShell(initial = "/") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <AppShell>
        <Routes>
          <Route path="/" element={<div>содержимое портфеля</div>} />
          <Route path="/assets" element={<div>содержимое активов</div>} />
        </Routes>
      </AppShell>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  it("показывает содержимое текущего экрана", () => {
    renderShell();
    expect(screen.getByText("содержимое портфеля")).toBeInTheDocument();
  });

  it("переводит на другой экран по ссылке", async () => {
    renderShell();

    await userEvent.click(screen.getByRole("link", { name: "Активы" }));

    expect(screen.getByText("содержимое активов")).toBeInTheDocument();
  });

  it("отмечает текущий пункт меню", async () => {
    // Иначе на четырёх экранах непонятно, где находишься.
    renderShell("/assets");
    expect(screen.getByRole("link", { name: "Активы" })).toHaveAttribute("aria-current", "page");
  });

  it("не показывает пункты экранов, которых ещё нет", () => {
    // Пункт, ведущий в пустоту, — обещание, которого система не выполняет.
    // Порядок и группировка восьми экранов решены в дизайне, но в меню
    // попадают только те, что есть чем наполнить.
    renderShell();

    expect(NAV_ITEMS.map((item) => item.title)).toEqual([
      "Портфель", "Активы", "Сделки и расхождения", "Настройки",
    ]);
    expect(screen.queryByRole("link", { name: "Налоги" })).not.toBeInTheDocument();
  });
});
