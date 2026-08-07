import { MoneyValue } from "./MoneyValue";
import type { Overview, SyncRunResult } from "../api/client";

const STATUS_LABEL: Record<string, string> = {
  success: "синхронизирован",
  failed: "ошибка синхронизации",
};

export function SummaryCard({ overview, onSync, syncing, syncResult, syncErrorMessage }: {
  overview: Overview;
  onSync: () => void;
  syncing: boolean;
  syncResult: SyncRunResult[] | null;
  syncErrorMessage: string | null;
}) {
  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12 }}>Совокупный капитал</div>
      <div style={{ fontSize: 34, fontWeight: 650, letterSpacing: "-0.025em", margin: "6px 0 14px" }}>
        <MoneyValue amount={overview.total_value} />
      </div>
      <button
        onClick={onSync}
        disabled={syncing}
        style={{
          border: "1px solid var(--line)", borderRadius: 9, padding: "7px 14px",
          background: "rgba(123,156,255,0.14)", color: "var(--blue)", cursor: "pointer",
        }}
      >
        {syncing ? "Синхронизация…" : "Обновить из Т-Банка"}
      </button>

      {syncErrorMessage && (
        <div style={{ color: "var(--red)", fontSize: 13, marginTop: 12 }}>{syncErrorMessage}</div>
      )}

      {syncResult && (
        <div style={{ marginTop: 14, display: "grid", gap: 6 }}>
          {syncResult.map((run) => (
            <div key={run.account} style={{ fontSize: 12.5 }}>
              <span style={{ color: run.status === "success" ? "var(--green)" : "var(--red)" }}>
                {run.status === "success" ? "✓" : "✕"}
              </span>{" "}
              <span style={{ color: "var(--tx-2)" }}>{run.account}:</span>{" "}
              {STATUS_LABEL[run.status] ?? run.status}
              {run.error && <div style={{ color: "var(--tx-2)", marginLeft: 18 }}>{run.error}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
