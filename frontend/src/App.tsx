import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PortfolioPage } from "./pages/PortfolioPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <PortfolioPage />
    </QueryClientProvider>
  );
}
