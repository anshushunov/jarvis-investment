import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";

import { AppShell } from "./app/AppShell";
import { AnimationProvider } from "./design/animation";
import { AssetsPage } from "./pages/AssetsPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TradesPage } from "./pages/TradesPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AnimationProvider>
        <BrowserRouter>
          <AppShell>
            <Routes>
              <Route path="/" element={<PortfolioPage />} />
              <Route path="/assets" element={<AssetsPage />} />
              <Route path="/trades" element={<TradesPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </AppShell>
        </BrowserRouter>
      </AnimationProvider>
    </QueryClientProvider>
  );
}
