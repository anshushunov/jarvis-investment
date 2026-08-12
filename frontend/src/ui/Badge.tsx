import { cva, type VariantProps } from "class-variance-authority";
import type { ReactNode } from "react";

// Метка статуса: расхождение с брокером, блокировка, происхождение точки.
// Цвет здесь несёт смысл, поэтому вариантов ровно столько, сколько различий.
const badge = cva("inline-block rounded-sm px-1.5 py-0.5 text-2xs", {
  variants: {
    tone: {
      neutral: "bg-muted/15 text-muted",
      warning: "bg-amber/15 text-amber",
      danger: "bg-red/15 text-red",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ tone, children }: { children: ReactNode } & VariantProps<typeof badge>) {
  return <span className={badge({ tone })}>{children}</span>;
}
