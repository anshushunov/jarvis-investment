import { TargetAllocationCard } from "../components/TargetAllocationCard";
import { useAnimationMode, type AnimationMode } from "../design/animation";
import { Card, CardTitle } from "../ui/Card";
import { SegmentedControl } from "../ui/SegmentedControl";

const MODES: { value: AnimationMode; label: string }[] = [
  { value: "off", label: "Выключены" },
  { value: "calm", label: "Сдержанные" },
  { value: "expressive", label: "Выразительные" },
];

export function SettingsPage() {
  const { mode, setMode, systemPrefersReduced } = useAnimationMode();

  return (
    <div className="grid gap-3.5">
      <Card>
        <CardTitle>Анимации</CardTitle>
        <SegmentedControl options={MODES} value={mode} onChange={setMode} name="animation-mode" />
        {systemPrefersReduced && (
          <div className="mt-2 text-xs text-muted">
            Система просит уменьшить движение — по умолчанию анимации выключены.
            Выбор здесь эту настройку перебивает.
          </div>
        )}
      </Card>
      <TargetAllocationCard />
    </div>
  );
}
