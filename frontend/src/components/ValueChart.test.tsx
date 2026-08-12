import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ValueChart } from "./ValueChart";
import type { HistoryPoint } from "../api/client";

// Настоящий ECharts в jsdom не рисует; проверяем то, что ему передано, —
// именно это и есть содержание графика.
const captured: { option: Record<string, unknown> | null } = { option: null };

vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: Record<string, unknown> }) => {
    captured.option = option;
    return <div data-testid="chart" />;
  },
}));

function point(overrides: Partial<HistoryPoint>): HistoryPoint {
  return {
    date: "2024-06-03",
    total_value: "1000.0000",
    by_account: {},
    source: "backfill",
    valued_positions: 2,
    positions_total: 2,
    unpriced: [],
    ...overrides,
  };
}

const FULL = point({ date: "2024-06-03" });
const PARTIAL = point({
  date: "2024-06-04",
  total_value: "900.0000",
  valued_positions: 1,
  positions_total: 2,
  unpriced: ["ТКС Холдинг"],
});

describe("ValueChart", () => {
  it("рисует линию по всем точкам", () => {
    render(<ValueChart points={[FULL, PARTIAL]} error={null} loading={false} />);

    const series = captured.option!.series as Array<{ type: string; data: unknown[] }>;
    expect(series[0].type).toBe("line");
    expect(series[0].data).toEqual([1000, 900]);
  });

  it("отмечает отдельной серией даты с неполной оценкой", () => {
    render(<ValueChart points={[FULL, PARTIAL]} error={null} loading={false} />);

    const series = captured.option!.series as Array<{ type: string; data: unknown[] }>;
    const incomplete = series.find((item) => item.type === "scatter")!;
    expect(incomplete.data).toEqual([[1, 900]]);
  });

  it("не отмечает точки, у которых покрытие неизвестно", () => {
    // У снимков, снятых до фазы 2c, покрытие не считали: NULL значит
    // «неизвестно», и объявлять их неполными — такое же враньё, как полными.
    const unknown = point({ valued_positions: null, positions_total: null });

    render(<ValueChart points={[FULL, unknown]} error={null} loading={false} />);

    const series = captured.option!.series as Array<{ type: string; data: unknown[] }>;
    expect(series.find((item) => item.type === "scatter")!.data).toEqual([]);
  });

  it("показывает график по одной точке", () => {
    // Заглушка про «накопится два снимка» после достройки перестала быть
    // правдой: история приходит целиком, а не копится по дню.
    render(<ValueChart points={[FULL]} error={null} loading={false} />);

    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });

  it("сбой запроса не выдаётся за отсутствие данных", () => {
    render(<ValueChart points={[]} error="сеть недоступна" loading={false} />);

    expect(screen.getByText(/сеть недоступна/)).toBeInTheDocument();
  });
});
