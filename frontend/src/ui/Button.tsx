import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

/**
 * Кнопка интерфейса.
 *
 * До фазы 3 стилизована была ровно одна кнопка из одиннадцати — остальные
 * рисовались системными кнопками браузера. Варианты здесь не украшение:
 * необратимое действие («Отклонить навсегда») обязано отличаться от обычного.
 */
const button = cva(
  "rounded-md border px-3.5 py-[7px] text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60",
  {
    variants: {
      variant: {
        primary: "border-line bg-blue/[0.14] text-blue hover:bg-blue/25",
        ghost: "border-line bg-transparent text-muted hover:text-tx",
        danger: "border-line bg-red/[0.12] text-red hover:bg-red/20",
      },
    },
    defaultVariants: { variant: "primary" },
  },
);

export function Button({ variant, className = "", type = "button", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>) {
  // type="button" по умолчанию: кнопки стоят рядом с полями ввода, и submit по
  // умолчанию отправлял бы форму при нажатии Enter в любом из них.
  return <button type={type} className={`${button({ variant })} ${className}`} {...rest} />;
}
