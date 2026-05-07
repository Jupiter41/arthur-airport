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
      { path: "/ml", label: "ML Training", icon: "🧠" },
      { path: "/data-sources", label: "Data Sources", icon: "🔌" },
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
        className={`text-sm font-medium px-3 py-1.5 rounded-xl transition-all duration-200 flex items-center gap-1.5 ${
          isActive
            ? "bg-accent/15 text-accent border border-accent/25"
            : "text-gray-400 hover:text-white hover:bg-panel-hover/60"
        }`}
      >
        <span className="text-base">{item.icon}</span>
        <span className="hidden lg:inline">{item.label}</span>
        <span
          className={`text-[10px] ml-0.5 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          ▾
        </span>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1.5 bg-surface-card/95 border border-panel-border rounded-xl shadow-xl shadow-black/40 z-50 min-w-[180px] py-1.5 backdrop-blur-md">
          {item.children.map((child) => (
            <NavLink
              key={child.path}
              to={child.path}
              onClick={() => setOpen(false)}
              className={({ isActive: active }) =>
                `flex items-center text-sm px-4 py-2 transition-colors rounded-lg mx-1.5 ${
                  active
                    ? "bg-accent/15 text-accent"
                    : "text-gray-300 hover:bg-panel-hover/60 hover:text-white"
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
    <header className="bg-surface-card/80 backdrop-blur-md border-b border-panel-border/60 shadow-lg shadow-black/20 relative z-[100] shrink-0">
      <div className="flex items-center justify-between px-4 h-12 gap-4">
        {/* Left: Logo + nav */}
        <div className="flex items-center gap-3 min-w-0">
          <NavLink to="/" className="flex items-center gap-2 shrink-0">
            <span className="text-lg">✈️</span>
            <span className="text-lg font-bold tracking-tight bg-gradient-to-r from-accent to-blue-300 bg-clip-text text-transparent">
              KART
            </span>
          </NavLink>

          <div className="h-5 w-px bg-panel-border/40 hidden md:block" />

          <nav className="flex items-center gap-0.5">
            {NAV_ITEMS.map((item) =>
              item.children ? (
                <NavDropdown key={item.label} item={item} />
              ) : (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `text-sm font-medium px-3 py-1.5 rounded-xl transition-all duration-200 whitespace-nowrap flex items-center gap-1.5 ${
                      isActive
                        ? "bg-accent/15 text-accent border border-accent/25"
                        : "text-gray-400 hover:text-white hover:bg-panel-hover/60"
                    }`
                  }
                  end={item.path === "/"}
                >
                  <span className="text-base">{item.icon}</span>
                  <span className="hidden lg:inline">{item.label}</span>
                </NavLink>
              ),
            )}
          </nav>
        </div>

        {/* Center: Weather (hidden on small screens) */}
        <div className="hidden xl:flex items-center min-w-0">
          <WeatherStrip />
        </div>

        {/* Right: status + controls */}
        <div className="flex items-center gap-2 shrink-0">
          <IncidentBadge />
          <ConnectionStatus />
          <div className="h-5 w-px bg-panel-border/40 hidden sm:block" />
          <SimClock />
          <SimControls />
          <div className="h-5 w-px bg-panel-border/40" />
          <button
            className="text-xs font-medium bg-panel hover:bg-panel-hover text-gray-300 px-3 py-1.5 rounded-lg transition-all duration-200 disabled:opacity-40 border border-panel-border hover:border-gray-500 flex items-center gap-1.5"
            onClick={handleGlobalExport}
            disabled={exporting}
            title="Export full simulation snapshot as JSON"
          >
            <span>{exporting ? "…" : "⬇"}</span>
            <span className="hidden sm:inline">Export</span>
          </button>
        </div>
      </div>
    </header>
  );
}
