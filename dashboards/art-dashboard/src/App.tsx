import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HeaderBar } from "./components/HeaderBar";
import { useWebSocket } from "./hooks/useWebSocket";
import FlightBoardPage from "./pages/FlightBoard/FlightBoardPage";
import BaggageTrackerPage from "./pages/BaggageTracker/BaggageTrackerPage";
import PassengerFlowPage from "./pages/PassengerFlow/PassengerFlowPage";
import IncidentConsolePage from "./pages/IncidentConsole/IncidentConsolePage";
import GroundOpsPage from "./pages/GroundOps/GroundOpsPage";
import SimHistoryPage from "./pages/SimHistory/SimHistoryPage";
import ScenariosPage from "./pages/Scenarios/ScenariosPage";
import SettingsPage from "./pages/Settings/SettingsPage";
import WorldMapPage from "./pages/WorldMap/WorldMapPage";
import DebugPage from "./pages/Debug/DebugPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 15_000,
      retry: 2,
      staleTime: 10_000,
      refetchOnWindowFocus: false,
    },
  },
});

function AppShell() {
  useWebSocket();

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white overflow-hidden">
      <HeaderBar />
      <main className="flex-1 min-h-0 overflow-hidden">
        <Routes>
          <Route path="/" element={<FlightBoardPage />} />
          <Route path="/baggage" element={<BaggageTrackerPage />} />
          <Route path="/passengers" element={<PassengerFlowPage />} />
          <Route path="/incidents" element={<IncidentConsolePage />} />
          <Route path="/ground-ops" element={<GroundOpsPage />} />
          <Route path="/world" element={<WorldMapPage />} />
          <Route path="/history" element={<SimHistoryPage />} />
          <Route path="/scenarios" element={<ScenariosPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/debug" element={<DebugPage />} />
        </Routes>
      </main>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
