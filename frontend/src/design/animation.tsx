import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export type AnimationMode = "off" | "calm" | "expressive";

export const ANIMATION_STORAGE_KEY = "jarvis.animation";

// Длительность перетекания числа, мс. Ноль — значение ставится сразу.
const DURATION: Record<AnimationMode, number> = { off: 0, calm: 400, expressive: 900 };

function systemReduced(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function initialMode(): AnimationMode {
  const stored = localStorage.getItem(ANIMATION_STORAGE_KEY) as AnimationMode | null;
  // Явный выбор владельца перебивает системную настройку: пользователь один, и
  // переключатель, который не работает, хуже отсутствующего. Системная
  // настройка задаёт умолчание — и об этом сказано на экране настроек.
  if (stored === "off" || stored === "calm" || stored === "expressive") return stored;
  return systemReduced() ? "off" : "calm";
}

const AnimationContext = createContext<{
  mode: AnimationMode;
  setMode: (mode: AnimationMode) => void;
  systemPrefersReduced: boolean;
} | null>(null);

export function AnimationProvider({ children }: { children: ReactNode }) {
  const [mode, setStoredMode] = useState<AnimationMode>(initialMode);

  const setMode = (next: AnimationMode) => {
    localStorage.setItem(ANIMATION_STORAGE_KEY, next);
    setStoredMode(next);
  };

  return (
    <AnimationContext.Provider value={{ mode, setMode, systemPrefersReduced: systemReduced() }}>
      {children}
    </AnimationContext.Provider>
  );
}

export function useAnimationMode() {
  const value = useContext(AnimationContext);
  if (value === null) throw new Error("useAnimationMode вне AnimationProvider");
  return value;
}

/**
 * Число, перетекающее к новому значению.
 *
 * Библиотека анимаций для этого не нужна: перетекание одно на весь интерфейс,
 * и оно выражается счётчиком на requestAnimationFrame. Появится морфинг линии
 * графика и выезд панели чата — появится и основание для зависимости.
 */
export function useAnimatedNumber(target: number): number {
  const { mode } = useAnimationMode();
  const [value, setValue] = useState(target);
  const from = useRef(target);

  useEffect(() => {
    const duration = DURATION[mode];
    if (duration === 0) {
      from.current = target;
      setValue(target);
      return;
    }

    // Начало отсчёта берётся из первого кадра, а не из performance.now():
    // таймстемп requestAnimationFrame живёт в своей шкале, и в jsdom она
    // отстаёт от performance.now() на сотню миллисекунд — доля пути выходила
    // отрицательной, и цифра сперва уезжала в минус.
    let start: number | null = null;
    const origin = from.current;
    let frame = 0;

    const step = (now: number) => {
      start ??= now;
      const passed = Math.min((now - start) / duration, 1);
      // Замедление к концу: значение приезжает мягко, а не втыкается.
      const eased = 1 - (1 - passed) ** 3;
      setValue(origin + (target - origin) * eased);
      if (passed < 1) frame = requestAnimationFrame(step);
      else from.current = target;
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, mode]);

  return value;
}
