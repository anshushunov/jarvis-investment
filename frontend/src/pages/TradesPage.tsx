import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { SyncRunResult } from "../api/client";
import { ReconciliationBanner } from "../components/ReconciliationBanner";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";

const STATUS_LABEL: Record<string, string> = {
  success: "синхронизирован",
  failed: "ошибка синхронизации",
};

// Итог прогона по каждому счёту отдельно: у владельца их пять, и «готово» одной
// строкой скрыло бы счёт, на котором синхронизация не прошла.
function SyncReport({ runs }: { runs: SyncRunResult[] }) {
  return (
    <div className="mt-3.5 grid gap-1.5">
      {runs.map((run) => (
        <div key={run.account} className="text-xs">
          <span className={run.status === "success" ? "text-green" : "text-red"}>
            {run.status === "success" ? "✓" : "✕"}
          </span>{" "}
          <span className="text-muted">{run.account}:</span>{" "}
          {STATUS_LABEL[run.status] ?? run.status}
          {run.error && <div className="ml-[18px] text-muted">{run.error}</div>}
        </div>
      ))}
    </div>
  );
}

export function TradesPage() {
  const queryClient = useQueryClient();
  const reconciliations = useQuery({
    queryKey: ["reconciliations"],
    queryFn: api.reconciliations,
  });

  // Синхронизация переехала сюда со сводки капитала: она про движение данных,
  // а не про их итог, и её место рядом с расхождениями, которые она порождает.
  const sync = useMutation({
    mutationFn: api.syncTbank,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  return (
    <div className="grid gap-3.5">
      <Card>
        <Button onClick={() => sync.mutate()} disabled={sync.isPending}>
          {sync.isPending ? "Синхронизация…" : "Обновить из Т-Банка"}
        </Button>
        {sync.isError && (
          <div className="mt-2 text-sm text-red">{(sync.error as Error).message}</div>
        )}
        {sync.data && <SyncReport runs={sync.data} />}
      </Card>

      <ReconciliationBanner
        rows={reconciliations.data ?? []}
        error={reconciliations.isError ? (reconciliations.error as Error).message : null}
      />
    </div>
  );
}
