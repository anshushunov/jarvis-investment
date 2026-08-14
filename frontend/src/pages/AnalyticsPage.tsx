import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type ReturnsPeriod } from "../api/client";
import { ReturnsSummary } from "../components/ReturnsSummary";
import { CardState } from "../ui/CardState";
import { SegmentedControl } from "../ui/SegmentedControl";

const PERIODS: { value: ReturnsPeriod; label: string }[] = [
  { value: "all", label: "Всё время" },
  { value: "12m", label: "12 месяцев" },
  { value: "ytd", label: "С начала года" },
];

export function AnalyticsPage() {
  // Период — состояние экрана, а не часть адреса: то же решение, что на
  // «Портфеле» с переключателем графика.
  const [period, setPeriod] = useState<ReturnsPeriod>("all");
  const returns = useQuery({
    queryKey: ["returns", period],
    queryFn: () => api.returns(period),
  });

  if (returns.isPending) return <CardState kind="loading">Загрузка…</CardState>;
  if (returns.isError) {
    return <CardState kind="error">{(returns.error as Error).message}</CardState>;
  }

  return (
    <div className="grid gap-3.5">
      <SegmentedControl options={PERIODS} value={period} onChange={setPeriod} />
      <ReturnsSummary returns={returns.data} />
    </div>
  );
}
