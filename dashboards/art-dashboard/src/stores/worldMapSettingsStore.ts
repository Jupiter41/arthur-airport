import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export type FlightFilter = "all" | "departures" | "arrivals";
export type MapStyle = "satellite" | "dark" | "streets";
export type StatusFilter = "all" | "airborne" | "boarding" | "ground";
export type DataSource = "all" | "simulated" | "real";

interface WorldMapSettingsState {
  showAdsb: boolean;
  showRoutes: boolean;
  showNetwork: boolean;
  showSearchPanel: boolean;
  showControlPanel: boolean;
  flightFilter: FlightFilter;
  statusFilter: StatusFilter;
  dataSource: DataSource;
  mapStyle: MapStyle;

  setShowAdsb: (value: boolean) => void;
  setShowRoutes: (value: boolean) => void;
  setShowNetwork: (value: boolean) => void;
  setShowSearchPanel: (value: boolean) => void;
  setShowControlPanel: (value: boolean) => void;
  setFlightFilter: (value: FlightFilter) => void;
  setStatusFilter: (value: StatusFilter) => void;
  setDataSource: (value: DataSource) => void;
  setMapStyle: (value: MapStyle) => void;
}

export const useWorldMapSettingsStore = create<WorldMapSettingsState>()(
  persist(
    (set) => ({
      showAdsb: false,
      showRoutes: true,
      showNetwork: false,
      showSearchPanel: false,
      showControlPanel: false,
      flightFilter: "all",
      statusFilter: "all",
      dataSource: "all",
      mapStyle: "satellite",
      setShowAdsb: (value) => set({ showAdsb: value }),
      setShowRoutes: (value) => set({ showRoutes: value }),
      setShowNetwork: (value) => set({ showNetwork: value }),
      setShowSearchPanel: (value) => set({ showSearchPanel: value }),
      setShowControlPanel: (value) => set({ showControlPanel: value }),
      setFlightFilter: (value) => set({ flightFilter: value }),
      setStatusFilter: (value) => set({ statusFilter: value }),
      setDataSource: (value) => set({ dataSource: value }),
      setMapStyle: (value) => set({ mapStyle: value }),
    }),
    {
      name: "art-worldmap-settings",
      storage: createJSONStorage(() => localStorage),
      version: 2,
    },
  ),
);
