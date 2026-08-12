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

// Горизонтальных отступов у ячеек нет намеренно: восемь колонок таблицы
// позиций и без них занимают всю ширину карточки, а padding по 8px с каждой
// стороны выталкивал колонку «Результат» за её край.
export function Th({ children, numeric = false }: { children: ReactNode; numeric?: boolean }) {
  return (
    <th
      className={`border-b border-line py-2 pr-2 font-normal text-xs text-muted last:pr-0 ${
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
    <td className={`border-b border-line py-2 pr-2 last:pr-0 ${numeric ? "text-right tabular-nums" : ""}`}>
      {children}
    </td>
  );
}
