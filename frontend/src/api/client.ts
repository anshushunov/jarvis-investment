// Бэкенд на хосте слушает порт 8001 (порт 8000 занят посторонним контейнером).
const BASE = "http://localhost:8001/api";

export interface Overview {
  total_value: string;
  positions_value: string;
  by_asset_class: Record<string, string>;
  by_account: Record<string, string>;
  // Дата актуальности оценки; пусто, если котировок ещё нет.
  as_of: string | null;
}

export interface PositionRow {
  isin: string | null;
  ticker: string | null;
  name: string;
  broker: string;
  quantity: string;
  average_price: string;
  last_price: string | null;
  market_value: string;
  profit: string;
  profit_percent: string;
}

export interface HistoryPoint {
  date: string;
  total_value: string;
}

export interface ReconciliationRow {
  isin: string | null;
  status: string;
  ledger_quantity: string;
  broker_quantity: string;
}

export interface SyncRunResult {
  // Подпись счёта, по которому прошёл этот прогон синхронизации.
  account: string;
  broker: string;
  status: string;
  inserted: number;
  skipped: number;
  mismatches: number;
  error: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    throw new Error(`Запрос ${path} завершился с кодом ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  overview: () => request<Overview>("/portfolio/overview"),
  positions: () => request<PositionRow[]>("/portfolio/positions"),
  history: (days = 90) => request<HistoryPoint[]>(`/portfolio/history?days=${days}`),
  reconciliations: () => request<ReconciliationRow[]>("/reconciliations"),
  syncTbank: () => request<SyncRunResult[]>("/sync/tbank", { method: "POST" }),
};
