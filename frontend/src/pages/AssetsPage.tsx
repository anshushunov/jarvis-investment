import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { PositionsTable } from "../components/PositionsTable";

export function AssetsPage() {
  const positions = useQuery({ queryKey: ["positions"], queryFn: api.positions });

  return (
    <PositionsTable
      rows={positions.data ?? []}
      error={positions.isError ? (positions.error as Error).message : null}
      loading={positions.isPending}
    />
  );
}
