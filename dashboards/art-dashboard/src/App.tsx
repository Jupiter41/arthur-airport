import { BrowserRouter, Routes, Route } from "react-router-dom";
import { HeaderBar } from "./components/HeaderBar";
import { useWebSocket } from "./hooks/useWebSocket";
import FlightBoardPage from "./pages/FlightBoard/FlightBoardPage";
import BaggageTrackerPage from "./pages/BaggageTracker/BaggageTrackerPage";
import PassengerFlowPage from "./pages/PassengerFlow/PassengerFlowPage";
import IncidentConsolePage from "./pages/IncidentConsole/IncidentConsolePage";
import GroundOpsPage from "./pages/GroundOps/GroundOpsPage";

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
        </Routes>
      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}

export default App;
