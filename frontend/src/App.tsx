import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnimationProvider } from "./design/animation";
import { PortfolioPage } from "./pages/PortfolioPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AnimationProvider>
        <PortfolioPage />
      </AnimationProvider>
    </QueryClientProvider>
  );
}
