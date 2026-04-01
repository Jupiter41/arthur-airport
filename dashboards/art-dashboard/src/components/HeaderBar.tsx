import { useState, useCallback, useRef, useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
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

type NavItem =
  | { path: string; label: string; icon: string; children?: undefined }
  | {
      label: string;
      icon: string;
      children: { path: string; label: string; icon: string }[];
      path?: undefined;
    };

const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Flights", icon: "✈️" },
  {
    label: "Terminal",
    icon: "🏢",
    children: [
      { path: "/passengers", label: "Passengers", icon: "👥" },
      { path: "/baggage", label: "Baggage", icon: "🧳" },
    ],
  },
  { path: "/incidents", label: "Incidents", icon: "🚨" },
  {
    label: "Ops",
    icon: "🎛️",
    children: [
      { path: "/ground-ops", label: "Ground Ops", icon: "🛬" },
      { path: "/world", label: "World", icon: "🗺️" },
    ],
  },
  {
    label: "Simulation",
    icon: "⚙️",
    children: [
      { path: "/history", label: "History", icon: "📊" },
      { path: "/scenarios", label: "Scenarios", icon: "🧪" },
      { path: "/settings", label: "Settings", icon: "⚙️" },
    ],
  },
];

function NavDropdown({
  item,
}: {
  item: Extract<NavItem, { children: unknown[] }>;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const isActive = item.children.some((c) => c.path === location.pathname);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`text-xs font-medium px-3 py-1.5 rounded-t transition-colors flex items-center gap-1 ${
          isActive
            ? "bg-gray-900 text-white border-t-2 border-blue-400"
            : "text-gray-400 hover:text-white hover:bg-gray-700"
        }`}
      >
        <span>{item.icon}</span>
        {item.label}
        <span className="text-[10px] ml-0.5">▾</span>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0 bg-gray-800 border border-gray-700 rounded-b shadow-lg z-50 min-w-[160px]">
          {item.children.map((child) => (
            <NavLink
              key={child.path}
              to={child.path}
              onClick={() => setOpen(false)}
              className={({ isActive: active }) =>
                `block text-xs px-4 py-2 transition-colors ${
                  active
                    ? "bg-gray-700 text-blue-400"
                    : "text-gray-300 hover:bg-gray-700 hover:text-white"
                }`
              }
            >
              <span className="mr-2">{child.icon}</span>
              {child.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

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
        {NAV_ITEMS.map((item) =>
          item.children ? (
            <NavDropdown key={item.label} item={item} />
          ) : (
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
          ),
        )}
      </nav>
    </header>
  );
}
