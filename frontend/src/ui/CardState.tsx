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

/**
 * Сообщение о состоянии без подложки — для карточек, у которых есть своя
 * шапка: график стоимости держит в ней переключатель периода, и прятать его
 * на время загрузки нельзя, иначе из выбранного периода не выбраться.
 */
export function StateMessage({ kind, children }: {
  kind: keyof typeof TONE;
  children: ReactNode;
}) {
  // role="status" — чтобы состояние читалось с экрана, а не только
  // различалось цветом.
  return <div role="status" className={`text-sm ${TONE[kind]}`}>{children}</div>;
}

export function CardState({ kind, children }: {
  kind: keyof typeof TONE;
  children: ReactNode;
}) {
  return (
    <Card>
      <StateMessage kind={kind}>{children}</StateMessage>
    </Card>
  );
}
