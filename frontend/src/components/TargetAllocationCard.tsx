import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type AllocationTargetInput } from "../api/client";
import { Card, CardTitle } from "../ui/Card";
import { StateMessage } from "../ui/CardState";
import { TargetAllocationForm } from "./TargetAllocationForm";

export function TargetAllocationCard() {
  const queryClient = useQueryClient();
  const targets = useQuery({ queryKey: ["allocation-targets"], queryFn: api.allocationTargets });
  // Тот же ключ, что у экрана «Активы»: один запрос на оба экрана.
  const positions = useQuery({ queryKey: ["positions"], queryFn: api.positions });
  const save = useMutation({
    mutationFn: (body: AllocationTargetInput[]) => api.saveAllocationTargets(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["allocation-targets"] }),
  });

  return (
    <Card>
      <CardTitle>Целевые доли</CardTitle>
      <div className="mb-3 text-xs text-muted">
        Доля от всего портфеля на класс активов или на бумагу. Сумма не обязана быть сотней:
        остаток — группа «не задано». Ассистент сравнивает с целями факт и считает, сколько докинуть.
      </div>
      {targets.isPending || positions.isPending ? (
        <StateMessage kind="loading">Загрузка…</StateMessage>
      ) : targets.isError || positions.isError ? (
        <StateMessage kind="error">{((targets.error ?? positions.error) as Error).message}</StateMessage>
      ) : (
        // key сбрасывает форму после сохранения: строки перечитываются из ответа.
        <TargetAllocationForm
          key={targets.dataUpdatedAt}
          targets={targets.data}
          positions={positions.data}
          onSave={(body) => save.mutate(body)}
          saving={save.isPending}
          error={save.isError ? (save.error as Error).message : null}
        />
      )}
    </Card>
  );
}
