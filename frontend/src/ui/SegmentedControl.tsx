/**
 * Группа взаимоисключающих переключателей.
 *
 * Под капотом радиокнопки, а не кнопки: выбор одного из нескольких — это и
 * есть радиогруппа, и клавиатура со экранным диктором работают с ней сами.
 */
export function SegmentedControl<T extends string | number>({ options, value, onChange, name = "segmented" }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  name?: string;
}) {
  return (
    <div role="radiogroup" className="inline-flex gap-1 rounded-md border border-line p-0.5">
      {options.map((option) => (
        <label
          key={String(option.value)}
          className={`cursor-pointer rounded-sm px-2.5 py-1 text-xs ${
            option.value === value ? "bg-blue/[0.14] text-blue" : "text-muted hover:text-tx"
          }`}
        >
          <input
            type="radio"
            name={name}
            className="sr-only"
            checked={option.value === value}
            onChange={() => onChange(option.value)}
          />
          {option.label}
        </label>
      ))}
    </div>
  );
}
