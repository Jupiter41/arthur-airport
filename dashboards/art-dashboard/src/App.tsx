import { lazy, Suspense, useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./queryClient";
import { HeaderBar } from "./components/HeaderBar";
import { Sidebar } from "./components/Sidebar";
import { Dialog } from "./components/Dialog";
import { TeachingRunbook } from "./pages/Decisions/TeachingRunbook";
import { LabPage } from "./pages/IncidentConsole/LabPage";
import { OperationalView, LegacySpatialRedirect } from "./components/OperationalView";
import { WebSocketManager } from "./components/WebSocketManager";
import FlightBoardPage from "./pages/FlightBoard/FlightBoardPage";
const CockpitPage = lazy(() => import("./pages/Cockpit/CockpitPage"));
const DecisionsPage = lazy(() => import("./pages/Decisions/DecisionsPage"));

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
const AtcTrafficPage = lazy(() => import("./pages/Airport3D/AtcBoard"));
const SimHistoryPage = lazy(() => import("./pages/SimHistory/SimHistoryPage"));
const ScenariosPage = lazy(() => import("./pages/Scenarios/ScenariosPage"));
const SettingsPage = lazy(() => import("./pages/Settings/SettingsPage"));
const WorldMapPage = lazy(() => import("./pages/WorldMap/WorldMapPage"));
const DebugPage = lazy(() => import("./pages/Debug/DebugPage"));
const MLTrainingPage = lazy(() => import("./pages/MLTraining/MLTrainingPage"));
const DataSourcesPage = lazy(
  () => import("./pages/DataSources/DataSourcesPage"),
);
const CostDashboardPage = lazy(
  () => import("./pages/CostDashboard/CostDashboardPage"),
);
const PlanningPage = lazy(() => import("./pages/Planning/PlanningPage"));
const CarbonPage = lazy(() => import("./pages/Carbon/CarbonPage"));
const AccessibilityPage = lazy(
  () => import("./pages/Accessibility/AccessibilityPage"),
);
const WhatIfPage = lazy(() => import("./pages/WhatIf/WhatIfPage"));

const PageFallback = () => (
  <div className="flex items-center justify-center h-full text-gray-400">
    Loading…
  </div>
);

function AppShell() {
  const [menu, setMenu] = useState(false);
  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <div className="hidden lg:flex min-h-0"><Sidebar /></div>
      {menu && <Dialog title="Navigation" onClose={() => setMenu(false)}><Sidebar onNavigate={() => setMenu(false)} /></Dialog>}
      <div className="min-w-0 min-h-0 flex flex-col">
      <WebSocketManager />
      <HeaderBar onMenu={() => setMenu(true)} />
      <main id="main-content" tabIndex={-1} className="page-scroll">
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/" element={<CockpitPage />} />
            <Route path="/flights" element={<FlightBoardPage />} />
            <Route path="/decisions" element={<DecisionsPage />} />
            <Route path="/airport-3d" element={<LegacySpatialRedirect />} />
            <Route path="/baggage" element={<OperationalView view="baggage" title="Baggage operations"><BaggageTrackerPage /></OperationalView>} />
            <Route path="/passengers" element={<OperationalView view="passengers" title="Passenger flow"><PassengerFlowPage /></OperationalView>} />
            <Route path="/incidents" element={<IncidentConsolePage />} />
            <Route path="/ground-ops" element={<OperationalView view="airport" title="Ground operations"><GroundOpsPage /></OperationalView>} />
            <Route path="/atc" element={<OperationalView view="atc" title="Air traffic control"><AtcTrafficPage /></OperationalView>} />
            <Route path="/world" element={<WorldMapPage />} />
            <Route path="/history" element={<SimHistoryPage />} />
            <Route path="/scenarios" element={<ScenariosPage />} />
            <Route path="/help" element={<div className="page-container space-y-6"><h1>Help & teaching lab</h1><p className="text-gray-400">Use Operations to monitor the shared airport, Planning for isolated experiments, and System for simulation setup. Search with Ctrl/Cmd K. Board, Map and 3D retain the selected terminal and entity.</p><TeachingRunbook /></div>} />
            <Route path="/lab" element={<LabPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/debug" element={<DebugPage />} />
            <Route path="/ml" element={<MLTrainingPage />} />
            <Route path="/data-sources" element={<DataSourcesPage />} />
            <Route path="/costs" element={<CostDashboardPage />} />
            <Route path="/planning" element={<PlanningPage />} />
            <Route path="/carbon" element={<CarbonPage />} />
            <Route path="/accessibility" element={<AccessibilityPage />} />
            <Route path="/whatif" element={<WhatIfPage />} />
          <Route path="*" element={<div className="page-container"><h1>Page not found</h1><a href="/">Return to Overview</a></div>} />
          </Routes>
        </Suspense>
      </main>
      </div>
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
