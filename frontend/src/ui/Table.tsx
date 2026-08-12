import type { ReactNode } from "react";

/**
 * Таблица интерфейса.
 *
 * Числовые ячейки помечаются явно (numeric): табличные цифры и правый край —
 * не украшение, а требование спеки. У пропорционального шрифта единица уже
 * восьмёрки, и колонка сумм дёргается при каждом обновлении котировок.
 */
export function Table({ children }: { children: ReactNode }) {
  return <table className="w-full border-collapse text-sm">{children}</table>;
}

export function Th({ children, numeric = false }: { children: ReactNode; numeric?: boolean }) {
  return (
    <th
      className={`border-b border-line px-2 py-2 font-normal text-xs text-muted ${
        numeric ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

export function Td({ children, numeric = false }: { children: ReactNode; numeric?: boolean }) {
  // Прозрачность через модификатор (border-line/60) здесь не сработает: токен
  // `line` записан как rgba(), а Tailwind умеет подмешивать альфу только к
  // цветам, заданным в формате с <alpha-value>. Рамка та же, что у шапки.
  return (
    <td className={`border-b border-line px-2 py-2 ${numeric ? "text-right tabular-nums" : ""}`}>
      {children}
    </td>
  );
}
