import { useState, useCallback } from "react";
import { NavLink } from "react-router-dom";
import { SimClock } from "./SimClock";
import { WeatherStrip } from "./WeatherStrip";
import { IncidentBadge } from "./IncidentBadge";
import { SimControls } from "./SimControls";
import { ConnectionStatus } from "./ConnectionStatus";
import {
  airportApi,
  flightsApi,
  weatherApi,
  incidentsApi,
  passengersApi,
  baggageApi,
} from "../hooks/useApi";
import { exportRaw } from "../utils/exportData";

const NAV_ITEMS = [
  { path: "/", label: "Flights", icon: "✈️" },
  { path: "/baggage", label: "Baggage", icon: "🧳" },
  { path: "/passengers", label: "Passengers", icon: "👥" },
  { path: "/incidents", label: "Incidents", icon: "🚨" },
  { path: "/ground-ops", label: "Ground Ops", icon: "🎛️" },
  { path: "/history", label: "History", icon: "📊" },
];

export function HeaderBar() {
  const [exporting, setExporting] = useState(false);

  const handleGlobalExport = useCallback(async () => {
    setExporting(true);
    try {
      const [snapshot, flights, weather, incidents, paxSummary, bagSummary] =
        await Promise.all([
          airportApi.snapshot().catch(() => null),
          flightsApi.list({ limit: "500" }).catch(() => null),
          weatherApi.current().catch(() => null),
          incidentsApi.list({ limit: "100" }).catch(() => null),
          passengersApi.summary().catch(() => null),
          baggageApi.summary().catch(() => null),
        ]);
      const archive = {
        exported_at: new Date().toISOString(),
        airport_snapshot: snapshot,
        flights,
        weather,
        incidents,
        passenger_summary: paxSummary,
        baggage_summary: bagSummary,
      };
      exportRaw(archive, `kart-sim-export-${Date.now()}`);
    } finally {
      setExporting(false);
    }
  }, []);

  return (
    <header className="bg-gray-800 border-b border-gray-700">
      {/* Top row */}
      <div className="flex items-center justify-between px-4 py-2">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-lg">✈️</span>
            <span className="text-lg font-bold text-blue-400">KART</span>
            <span className="text-sm text-gray-400">
              Arthur International Airport
            </span>
          </div>
          <WeatherStrip />
        </div>

        <div className="flex items-center gap-4">
          <button
            className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-2.5 py-1.5 rounded transition-colors disabled:opacity-40"
            onClick={handleGlobalExport}
            disabled={exporting}
            title="Export full simulation snapshot"
          >
            {exporting ? "Exporting…" : "⬇ Full Export"}
          </button>
          <ConnectionStatus />
          <IncidentBadge />
          <SimClock />
          <SimControls />
        </div>
      </div>

      {/* Nav row */}
      <nav className="flex gap-1 px-4 pb-1">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `text-xs font-medium px-3 py-1.5 rounded-t transition-colors ${
                isActive
                  ? "bg-gray-900 text-white border-t-2 border-blue-400"
                  : "text-gray-400 hover:text-white hover:bg-gray-700"
              }`
            }
            end={item.path === "/"}
          >
            <span className="mr-1">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
