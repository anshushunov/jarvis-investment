import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatDate } from "../api/format";
import { AllocationChart } from "../components/AllocationChart";
import { CashCard } from "../components/CashCard";
import { PositionsTable } from "../components/PositionsTable";
import { ReconciliationBanner } from "../components/ReconciliationBanner";
import { SummaryCard } from "../components/SummaryCard";
import { ValueChart } from "../components/ValueChart";

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const positions = useQuery({ queryKey: ["positions"], queryFn: api.positions });
  const cash = useQuery({ queryKey: ["cash"], queryFn: api.cash });
  const history = useQuery({ queryKey: ["history"], queryFn: () => api.history() });
  const reconciliations = useQuery({ queryKey: ["reconciliations"], queryFn: api.reconciliations });

  const sync = useMutation({
    mutationFn: api.syncTbank,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  if (overview.isLoading) return <div style={{ padding: 32 }}>Загрузка…</div>;
  if (overview.isError) return <div style={{ padding: 32 }}>Бэкенд недоступен. Запущен ли он на порту 8001?</div>;

  const asOf = formatDate(overview.data!.as_of);
  // Сбой запроса — не то же самое, что легитимно пустой ответ (нет позиций,
  // нет истории, нет расхождений): каждый компонент получает сообщение об
  // ошибке отдельно и решает, как его показать, отличимо от пустого состояния.
  const positionsError = positions.isError ? (positions.error as Error).message : null;
  const cashError = cash.isError ? (cash.error as Error).message : null;
  const historyError = history.isError ? (history.error as Error).message : null;
  const reconciliationsError = reconciliations.isError ? (reconciliations.error as Error).message : null;

  // Пока запрос ещё идёт, у него нет данных — и без этого признака компонент
  // показывал своё пустое состояние («позиций пока нет», «график появится,
  // когда накопится два снимка»). Сводка грузится быстрее остальных запросов,
  // так что на долю секунды после её ответа заглушка успевала мелькнуть: тот
  // же класс лжи пустым состоянием, что уже чинили для ошибок запроса.

  return (
    <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px", display: "grid", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h1 style={{ fontSize: 22, fontWeight: 640, margin: 0 }}>Портфель</h1>
        <span style={{ fontSize: 12.5, color: "var(--tx-2)" }}>
          {asOf ? `данные на ${asOf}` : "данные ещё не рассчитаны — нет котировок"}
          {overview.data!.fx_as_of ? ` · курсы на ${formatDate(overview.data!.fx_as_of)}` : ""}
        </span>
      </div>

      <ReconciliationBanner rows={reconciliations.data ?? []} error={reconciliationsError} />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 14 }}>
        <div style={{ display: "grid", gap: 14 }}>
          <SummaryCard
            overview={overview.data!}
            onSync={() => sync.mutate()}
            syncing={sync.isPending}
            syncResult={sync.data ?? null}
            syncErrorMessage={sync.isError ? (sync.error as Error).message : null}
          />
          <CashCard rows={cash.data ?? []} error={cashError} loading={cash.isPending} />
        </div>
        <ValueChart points={history.data ?? []} error={historyError} loading={history.isPending} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 14 }}>
        <AllocationChart data={overview.data!.by_asset_class} />
        <PositionsTable rows={positions.data ?? []} error={positionsError} loading={positions.isPending} />
      </div>
    </div>
  );
}
