import { memo } from "react";
import { useWorldMapSettingsStore } from "../stores/worldMapSettingsStore";
import type {
  FlightFilter,
  MapStyle,
  StatusFilter,
  DataSource,
} from "../stores/worldMapSettingsStore";

interface MapControlPanelProps {
  hasMapboxToken: boolean;
  adsbCount?: number;
  networkCount?: number;
  onClose: () => void;
}

/**
 * Unified control panel for the World Map page.
 *
 * Single entry point for all map settings: map style, data layers,
 * flight filters, and display options. Replaces scattered toolbar toggles.
 */
function MapControlPanelInner({
  hasMapboxToken,
  adsbCount,
  networkCount,
  onClose,
}: MapControlPanelProps) {
  const showAdsb = useWorldMapSettingsStore((s) => s.showAdsb);
  const setShowAdsb = useWorldMapSettingsStore((s) => s.setShowAdsb);
  const showRoutes = useWorldMapSettingsStore((s) => s.showRoutes);
  const setShowRoutes = useWorldMapSettingsStore((s) => s.setShowRoutes);
  const showNetwork = useWorldMapSettingsStore((s) => s.showNetwork);
  const setShowNetwork = useWorldMapSettingsStore((s) => s.setShowNetwork);
  const flightFilter = useWorldMapSettingsStore((s) => s.flightFilter);
  const setFlightFilter = useWorldMapSettingsStore((s) => s.setFlightFilter);
  const statusFilter = useWorldMapSettingsStore((s) => s.statusFilter);
  const setStatusFilter = useWorldMapSettingsStore((s) => s.setStatusFilter);
  const dataSource = useWorldMapSettingsStore((s) => s.dataSource);
  const setDataSource = useWorldMapSettingsStore((s) => s.setDataSource);
  const mapStyle = useWorldMapSettingsStore((s) => s.mapStyle);
  const setMapStyle = useWorldMapSettingsStore((s) => s.setMapStyle);

  return (
    <aside className="absolute top-3 left-3 w-72 rounded-lg border border-slate-700 bg-slate-950/96 text-xs shadow-xl backdrop-blur-sm p-4 max-h-[80vh] overflow-y-auto z-20 animation-slide-right">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-100">Map Settings</h3>
        <button
          type="button"
          className="text-slate-400 hover:text-slate-200 transition-colors"
          onClick={onClose}
        >
          ✕
        </button>
      </div>

      {/* ── Map Style ── */}
      {hasMapboxToken && (
        <Section title="Map Style">
          <div className="grid grid-cols-3 gap-1">
            {(
              [
                { value: "satellite", label: "Satellite", icon: "🛰" },
                { value: "dark", label: "Dark", icon: "🌙" },
                { value: "streets", label: "Streets", icon: "🗺" },
              ] as const
            ).map((style) => (
              <button
                key={style.value}
                type="button"
                onClick={() => setMapStyle(style.value as MapStyle)}
                className={`px-2 py-1.5 rounded text-center transition-colors ${
                  mapStyle === style.value
                    ? "bg-cyan-600 text-white"
                    : "bg-slate-800 hover:bg-slate-700 text-slate-300"
                }`}
              >
                {style.icon} {style.label}
              </button>
            ))}
          </div>
        </Section>
      )}

      {/* ── Data Layers ── */}
      <Section title="Data Layers">
        <Toggle
          label="Route Lines"
          icon="✈"
          active={showRoutes}
          onChange={setShowRoutes}
        />
        <Toggle
          label={`ADS-B Live${showAdsb && adsbCount != null ? ` (${adsbCount})` : ""}`}
          icon="📡"
          active={showAdsb}
          onChange={setShowAdsb}
          accent="orange"
        />
        <Toggle
          label={`Network${showNetwork && networkCount != null ? ` (${networkCount})` : ""}`}
          icon="🌐"
          active={showNetwork}
          onChange={setShowNetwork}
          accent="emerald"
        />
      </Section>

      {/* ── Flight Filters ── */}
      <Section title="Flight Filters">
        <label className="block text-slate-400 mb-1">Direction</label>
        <select
          value={flightFilter}
          onChange={(e) => setFlightFilter(e.target.value as FlightFilter)}
          className="w-full px-2 py-1.5 rounded bg-slate-800 text-slate-200 border border-slate-700 text-xs focus:outline-none focus:ring-1 focus:ring-cyan-500 cursor-pointer mb-2"
        >
          <option value="all">All flights</option>
          <option value="departures">Departures only</option>
          <option value="arrivals">Arrivals only</option>
        </select>

        <label className="block text-slate-400 mb-1">Status</label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          className="w-full px-2 py-1.5 rounded bg-slate-800 text-slate-200 border border-slate-700 text-xs focus:outline-none focus:ring-1 focus:ring-cyan-500 cursor-pointer mb-2"
        >
          <option value="all">All statuses</option>
          <option value="airborne">Airborne only</option>
          <option value="boarding">Boarding only</option>
          <option value="ground">Ground only</option>
        </select>

        <label className="block text-slate-400 mb-1">Data Source</label>
        <select
          value={dataSource}
          onChange={(e) => setDataSource(e.target.value as DataSource)}
          className="w-full px-2 py-1.5 rounded bg-slate-800 text-slate-200 border border-slate-700 text-xs focus:outline-none focus:ring-1 focus:ring-cyan-500 cursor-pointer"
        >
          <option value="all">Simulated + Real</option>
          <option value="simulated">Simulated only</option>
          <option value="real">Real (ADS-B) only</option>
        </select>
      </Section>

      {/* Legend */}
      <div className="mt-3 pt-3 border-t border-slate-700 text-[10px] text-slate-500 space-y-1">
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-cyan-400" />
          Departures
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 ml-2" />
          Arrivals
          {showAdsb && (
            <>
              <span className="inline-block w-2 h-2 rounded-full bg-orange-400 ml-2" />
              Real (ADS-B)
            </>
          )}
        </div>
        <p>Settings persist across page reloads</p>
      </div>
    </aside>
  );
}

export const MapControlPanel = memo(MapControlPanelInner);

/* ── Sub-components ── */

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3">
      <h4 className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1.5">
        {title}
      </h4>
      {children}
    </div>
  );
}

function Toggle({
  label,
  icon,
  active,
  onChange,
  accent = "cyan",
}: {
  label: string;
  icon: string;
  active: boolean;
  onChange: (value: boolean) => void;
  accent?: "cyan" | "orange" | "emerald";
}) {
  const colors = {
    cyan: "bg-cyan-600",
    orange: "bg-orange-600",
    emerald: "bg-emerald-600",
  };

  return (
    <button
      type="button"
      onClick={() => onChange(!active)}
      className={`w-full flex items-center justify-between px-2 py-1.5 rounded mb-1 transition-colors ${
        active
          ? `${colors[accent]} text-white`
          : "bg-slate-800 hover:bg-slate-700 text-slate-300"
      }`}
    >
      <span>
        {icon} {label}
      </span>
      <span
        className={`w-8 h-4 rounded-full relative transition-colors ${
          active ? "bg-white/30" : "bg-slate-600"
        }`}
      >
        <span
          className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
            active ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </span>
    </button>
  );
}
