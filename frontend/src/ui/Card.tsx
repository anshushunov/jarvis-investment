import type { ReactNode } from "react";

/**
 * Подложка карточки — единственная на проект.
 *
 * Заменяет класс .card из theme.css: правило «как выглядит карточка» жило в
 * CSS, а отступы вокруг него дописывались инлайном в каждом файле по-своему.
 */
export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-lg border border-line bg-card px-5 py-[18px] backdrop-blur-[8px] ${className}`}
    >
      {children}
    </div>
  );
}

/** Подпись карточки. Повторялась в пяти файлах одинаковым инлайновым стилем. */
export function CardTitle({ children }: { children: ReactNode }) {
  return <div className="mb-2 text-xs text-muted">{children}</div>;
}
