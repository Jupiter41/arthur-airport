import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HeaderBar } from "./components/HeaderBar";
import { WebSocketManager } from "./components/WebSocketManager";
import FlightBoardPage from "./pages/FlightBoard/FlightBoardPage";

// Lazy-load heavyweight pages to reduce initial bundle (~1.5MB savings)
const BaggageTrackerPage = lazy(
  () => import("./pages/BaggageTracker/BaggageTrackerPage"),
);
const PassengerFlowPage = lazy(
  () => import("./pages/PassengerFlow/PassengerFlowPage"),
);
const IncidentConsolePage = lazy(
  () => import("./pages/IncidentConsole/IncidentConsolePage"),
);
const GroundOpsPage = lazy(() => import("./pages/GroundOps/GroundOpsPage"));
const SimHistoryPage = lazy(() => import("./pages/SimHistory/SimHistoryPage"));
const ScenariosPage = lazy(() => import("./pages/Scenarios/ScenariosPage"));
const SettingsPage = lazy(() => import("./pages/Settings/SettingsPage"));
const WorldMapPage = lazy(() => import("./pages/WorldMap/WorldMapPage"));
const DebugPage = lazy(() => import("./pages/Debug/DebugPage"));
const MLTrainingPage = lazy(() => import("./pages/MLTraining/MLTrainingPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 15_000,
      retry: 2,
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      refetchIntervalInBackground: false,
    },
  },
});

const PageFallback = () => (
  <div className="flex items-center justify-center h-full text-gray-400">
    Loading…
  </div>
);

function AppShell() {
  return (
    <div className="h-screen flex flex-col bg-surface text-white overflow-hidden">
      <WebSocketManager />
      <HeaderBar />
      <main className="flex-1 min-h-0 overflow-hidden">
        <Suspense fallback={<PageFallback />}>
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
            <Route path="/ml" element={<MLTrainingPage />} />
          </Routes>
        </Suspense>
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
