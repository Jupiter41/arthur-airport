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
      { path: "/debug", label: "Debug", icon: "🛠️" },
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
        className={`text-sm font-medium px-3.5 py-2 rounded-lg transition-all duration-150 flex items-center gap-1.5 ${
          isActive
            ? "bg-gray-900 text-white shadow-inner border border-blue-500/30"
            : "text-gray-300 hover:text-white hover:bg-gray-700/60"
        }`}
      >
        <span className="text-base">{item.icon}</span>
        {item.label}
        <span
          className={`text-[10px] ml-0.5 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        >
          ▾
        </span>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-gray-800 border border-gray-600 rounded-lg shadow-xl shadow-black/30 z-50 min-w-[180px] py-1 backdrop-blur-sm">
          {item.children.map((child) => (
            <NavLink
              key={child.path}
              to={child.path}
              onClick={() => setOpen(false)}
              className={({ isActive: active }) =>
                `flex items-center text-sm px-4 py-2.5 transition-colors ${
                  active
                    ? "bg-blue-500/15 text-blue-400 border-l-2 border-blue-400"
                    : "text-gray-300 hover:bg-gray-700/60 hover:text-white border-l-2 border-transparent"
                }`
              }
            >
              <span className="mr-2.5 text-base">{child.icon}</span>
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
    <header className="bg-gray-800/95 backdrop-blur-sm border-b border-gray-700/80 shadow-lg shadow-black/20">
      {/* Top row */}
      <div className="flex items-center justify-between px-5 py-2.5">
        <div className="flex items-center gap-5">
          <div className="flex items-center gap-2.5">
            <span className="text-xl">✈️</span>
            <span className="text-xl font-bold tracking-tight text-blue-400">
              KART
            </span>
            <span className="text-sm text-gray-400 hidden sm:inline">
              Arthur International Airport
            </span>
          </div>
          <div className="hidden md:block">
            <WeatherStrip />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            className="text-xs font-medium bg-gray-700 hover:bg-gray-600 text-gray-200 px-3 py-2 rounded-lg transition-all duration-150 disabled:opacity-40 border border-gray-600 hover:border-gray-500"
            onClick={handleGlobalExport}
            disabled={exporting}
            title="Export full simulation snapshot"
          >
            {exporting ? "Exporting…" : "⬇ Export"}
          </button>
          <ConnectionStatus />
          <IncidentBadge />
          <SimClock />
          <SimControls />
        </div>
      </div>

      {/* Nav row */}
      <nav className="flex items-center gap-1 px-5 pb-2">
        {NAV_ITEMS.map((item) =>
          item.children ? (
            <NavDropdown key={item.label} item={item} />
          ) : (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `text-sm font-medium px-3.5 py-2 rounded-lg transition-all duration-150 ${
                  isActive
                    ? "bg-gray-900 text-white shadow-inner border border-blue-500/30"
                    : "text-gray-300 hover:text-white hover:bg-gray-700/60"
                }`
              }
              end={item.path === "/"}
            >
              <span className="mr-1.5 text-base">{item.icon}</span>
              {item.label}
            </NavLink>
          ),
        )}
      </nav>
    </header>
  );
}
