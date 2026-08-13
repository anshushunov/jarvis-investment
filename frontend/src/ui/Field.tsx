import type { InputHTMLAttributes, LabelHTMLAttributes } from "react";

/**
 * Поле ввода. До фазы 3 стилей не имело ни одно из четырнадцати.
 *
 * tabular-nums здесь по той же причине, что и в таблице позиций: в полях
 * набираются количества и цены, и они должны стоять в тех же колонках.
 */
export function Field({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`rounded-sm border border-line bg-bg1/60 px-2.5 py-1.5 text-sm text-tx tabular-nums outline-none focus:border-blue disabled:opacity-60 ${className}`}
      {...rest}
    />
  );
}

export function FieldLabel({ className = "", ...rest }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={`text-xs text-muted ${className}`} {...rest} />;
}
