import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "../api/client";
import { AllocationChart } from "../components/AllocationChart";
import { AsOfLabel } from "../components/AsOfLabel";
import { CashCard } from "../components/CashCard";
import { SummaryCard } from "../components/SummaryCard";
import { ValueChart } from "../components/ValueChart";
import { Card } from "../ui/Card";
import { CardState } from "../ui/CardState";
import { SegmentedControl } from "../ui/SegmentedControl";

// После достройки истории график рисует больше двух тысяч точек одной линией —
// отдельный год в ней не разглядеть.
const PERIODS = [
  { value: 30, label: "Месяц" },
  { value: 365, label: "Год" },
  { value: 0, label: "Всё время" },
];

export function PortfolioPage() {
  // Период — состояние экрана, а не часть адреса: это не место, а взгляд на
  // него.
  const [days, setDays] = useState(0);

  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const cash = useQuery({ queryKey: ["cash"], queryFn: api.cash });
  // 0 — «всё время»: бэкенд без параметра days отдаёт весь период (фаза 2c).
  const history = useQuery({
    queryKey: ["history", days],
    queryFn: () => api.history(days || undefined),
  });
  const reconciliations = useQuery({ queryKey: ["reconciliations"], queryFn: api.reconciliations });
  // Тот же обработчик и тот же ключ кэша, что на «Аналитике» (period="all"):
  // отдельной ручки под две цифры не существует, а TanStack Query отдаёт
  // ответ из кэша при переходе между экранами вместо повторного запроса.
  const returns = useQuery({ queryKey: ["returns", "all"], queryFn: () => api.returns("all") });

  if (overview.isLoading) return <CardState kind="loading">Загрузка…</CardState>;
  if (overview.isError) {
    return (
      <CardState kind="error">Бэкенд недоступен. Запущен ли он на порту 8001?</CardState>
    );
  }

  // Сбой запроса — не то же самое, что легитимно пустой ответ (нет позиций,
  // нет истории, нет расхождений): каждый компонент получает сообщение об
  // ошибке отдельно и решает, как его показать, отличимо от пустого состояния.
  const cashError = cash.isError ? (cash.error as Error).message : null;
  const historyError = history.isError ? (history.error as Error).message : null;

  // Пока запрос ещё идёт, у него нет данных — и без этого признака компонент
  // показывал своё пустое состояние («позиций пока нет», «график появится,
  // когда накопится два снимка»). Сводка грузится быстрее остальных запросов,
  // так что на долю секунды после её ответа заглушка успевала мелькнуть: тот
  // же класс лжи пустым состоянием, что уже чинили для ошибок запроса.

  return (
    <div className="grid gap-3.5">
      <AsOfLabel asOf={overview.data!.as_of} fxAsOf={overview.data!.fx_as_of} />

      {/* Расхождения на этом экране только объявляются числом: разбор — работа
          отдельная и долгая, и её место там, где живут сделки. */}
      {(reconciliations.data?.length ?? 0) > 0 && (
        <Card>
          <div className="flex items-center justify-between text-sm">
            <span>Расхождения с данными брокера: {reconciliations.data?.length ?? 0}</span>
            <Link to="/trades" className="text-blue">разобрать</Link>
          </div>
        </Card>
      )}

      {/* Колонка со сводкой шире прежней (2fr к 3fr, а не 1fr к 2fr): боковое
          меню забрало 190px, и при старой пропорции «Бумаги … · деньги …»
          переносилось на вторую строку. */}
      <div className="grid grid-cols-[2fr_3fr] gap-3.5">
        <div className="grid gap-3.5">
          <SummaryCard overview={overview.data!} returns={returns.data?.portfolio ?? null} />
          <CashCard rows={cash.data ?? []} error={cashError} loading={cash.isPending} />
        </div>
        <ValueChart
          points={history.data ?? []}
          error={historyError}
          loading={history.isPending}
          action={<SegmentedControl options={PERIODS} value={days} onChange={setDays} />}
        />
      </div>

      <AllocationChart data={overview.data!.by_asset_class} />
    </div>
  );
}
