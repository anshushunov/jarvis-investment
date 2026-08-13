import { describe, expect, it } from "vitest";

import { cssVariables, tokens } from "./tokens";

describe("токены", () => {
  it("не содержат двух цветов на один смысл", () => {
    // До этой фазы жёлтый был записан дважды: --amber #e8b04b в theme.css и
    // #e2b93b в ValueChart. Один смысл, два цвета — расхождение, которое
    // невозможно заметить глазом и нечем поймать, кроме такой проверки.
    expect(tokens.chart.incomplete).toBe(tokens.color.amber);
    expect(tokens.chart.line).toBe(tokens.color.blue);
    expect(tokens.chart.label).toBe(tokens.color.muted);
  });

  it("объявляют переменную на каждый цвет палитры", () => {
    // Плагин Tailwind объявляет их в :root — на них опирается theme.css.
    for (const [name, value] of Object.entries(tokens.color)) {
      expect(cssVariables).toHaveProperty(`--${kebab(name)}`, value);
    }
  });

  it("держат палитру классов активов отдельно от семантики", () => {
    // Цвет облигаций — не «предупреждение» и не «ошибка»: он про класс актива.
    // Сведение их к семантическим токенам заставило бы называть золото
    // «вниманием», и первый же новый класс сломал бы это соответствие.
    expect(Object.keys(tokens.assetClass)).toContain("bonds");
    expect(Object.values(tokens.color)).not.toContain(tokens.assetClass.bonds);
  });
});

function kebab(name: string): string {
  return name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}
