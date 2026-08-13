import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ANIMATION_STORAGE_KEY,
  AnimationProvider,
  useAnimatedNumber,
  useAnimationMode,
} from "./animation";

function mockReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches, media: query, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(),
  }));
}

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AnimationProvider>{children}</AnimationProvider>
);

describe("режим анимаций", () => {
  it("по умолчанию сдержанный", () => {
    mockReducedMotion(false);
    const { result } = renderHook(() => useAnimationMode(), { wrapper });
    expect(result.current.mode).toBe("calm");
  });

  it("выключен по умолчанию, когда система просит меньше движения", () => {
    mockReducedMotion(true);
    const { result } = renderHook(() => useAnimationMode(), { wrapper });
    expect(result.current.mode).toBe("off");
    expect(result.current.systemPrefersReduced).toBe(true);
  });

  it("выбор владельца перебивает системную настройку", () => {
    // Пользователь один, и он видит переключатель. Переключатель, который не
    // работает, хуже отсутствующего.
    mockReducedMotion(true);
    localStorage.setItem(ANIMATION_STORAGE_KEY, "expressive");

    const { result } = renderHook(() => useAnimationMode(), { wrapper });

    expect(result.current.mode).toBe("expressive");
  });

  it("запоминает выбор между запусками", () => {
    mockReducedMotion(false);
    const { result } = renderHook(() => useAnimationMode(), { wrapper });

    act(() => result.current.setMode("off"));

    expect(localStorage.getItem(ANIMATION_STORAGE_KEY)).toBe("off");
  });
});

function Counter({ value }: { value: number }) {
  return <span>{useAnimatedNumber(value)}</span>;
}

describe("перетекание числа", () => {
  it("при выключенных анимациях ставит значение сразу", () => {
    // Иначе тесты начнут ждать анимацию, а владелец с prefers-reduced-motion
    // увидит ползущую цифру там, где просил её не двигать.
    mockReducedMotion(true);

    render(<AnimationProvider><Counter value={11051805} /></AnimationProvider>);

    expect(screen.getByText("11051805")).toBeInTheDocument();
  });

  it("доводит число до конечного значения, а не останавливается на полпути", async () => {
    // Анимация обязана заканчиваться ровно на цели: цифра капитала, замершая
    // на 11 049 000 вместо 11 051 805, выглядит как настоящая.
    mockReducedMotion(false);

    const { rerender } = render(
      <AnimationProvider><Counter value={0} /></AnimationProvider>,
    );
    rerender(<AnimationProvider><Counter value={100} /></AnimationProvider>);

    await waitFor(() => expect(screen.getByText("100")).toBeInTheDocument());
  });
});
