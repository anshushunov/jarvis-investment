import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatDate } from "../api/format";
import { AllocationChart } from "../components/AllocationChart";
import { PositionsTable } from "../components/PositionsTable";
import { ReconciliationBanner } from "../components/ReconciliationBanner";
import { SummaryCard } from "../components/SummaryCard";
import { ValueChart } from "../components/ValueChart";

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const positions = useQuery({ queryKey: ["positions"], queryFn: api.positions });
  const history = useQuery({ queryKey: ["history"], queryFn: () => api.history(90) });
  const reconciliations = useQuery({ queryKey: ["reconciliations"], queryFn: api.reconciliations });

  const sync = useMutation({
    mutationFn: api.syncTbank,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  if (overview.isLoading) return <div style={{ padding: 32 }}>Загрузка…</div>;
  if (overview.isError) return <div style={{ padding: 32 }}>Бэкенд недоступен. Запущен ли он на порту 8001?</div>;

  const asOf = formatDate(overview.data!.as_of);

  return (
    <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px", display: "grid", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h1 style={{ fontSize: 22, fontWeight: 640, margin: 0 }}>Портфель</h1>
        <span style={{ fontSize: 12.5, color: "var(--tx-2)" }}>
          {asOf ? `данные на ${asOf}` : "данные ещё не рассчитаны — нет котировок"}
        </span>
      </div>

      {reconciliations.data && <ReconciliationBanner rows={reconciliations.data} />}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 14 }}>
        <SummaryCard
          overview={overview.data!}
          onSync={() => sync.mutate()}
          syncing={sync.isPending}
          syncResult={sync.data ?? null}
          syncErrorMessage={sync.isError ? (sync.error as Error).message : null}
        />
        <ValueChart points={history.data ?? []} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 14 }}>
        <AllocationChart data={overview.data!.by_asset_class} />
        <PositionsTable rows={positions.data ?? []} />
      </div>
    </div>
  );
}
