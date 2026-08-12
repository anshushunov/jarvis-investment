import { useAnimationMode, type AnimationMode } from "../design/animation";
import { Button } from "../ui/Button";
import { Card, CardTitle } from "../ui/Card";

const MODES: { value: AnimationMode; label: string }[] = [
  { value: "off", label: "Выключены" },
  { value: "calm", label: "Сдержанные" },
  { value: "expressive", label: "Выразительные" },
];

export function SettingsPage() {
  const { mode, setMode, systemPrefersReduced } = useAnimationMode();

  return (
    <Card>
      <CardTitle>Анимации</CardTitle>
      {/* Временно три кнопки: SegmentedControl появляется следующей задачей и
          заменит их, не меняя поведения. */}
      <div className="flex gap-2">
        {MODES.map((option) => (
          <Button
            key={option.value}
            variant={option.value === mode ? "primary" : "ghost"}
            onClick={() => setMode(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
      {systemPrefersReduced && (
        <div className="mt-2 text-xs text-muted">
          Система просит уменьшить движение — по умолчанию анимации выключены.
          Выбор здесь эту настройку перебивает.
        </div>
      )}
    </Card>
  );
}
