import type { ReactNode } from "react";

import { Card } from "./Card";

// Три состояния данных различаются и цветом, и текстом. Сбой запроса — не то
// же самое, что «данных нет», а идущий запрос — не то же самое, что пустой
// ответ: до фазы 2c компоненты путали их и показывали заглушку про
// синхронизацию, пока ответ был в пути.
const TONE = {
  loading: "text-muted",
  empty: "text-muted",
  error: "text-red",
} as const;

export function CardState({ kind, children }: {
  kind: keyof typeof TONE;
  children: ReactNode;
}) {
  return (
    <Card>
      {/* role="status" — чтобы состояние читалось с экрана, а не только
          различалось цветом. */}
      <div role="status" className={`text-sm ${TONE[kind]}`}>{children}</div>
    </Card>
  );
}
