import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export type FlightFilter = "all" | "departures" | "arrivals";
export type MapStyle = "satellite" | "dark" | "streets";

interface WorldMapSettingsState {
  showAdsb: boolean;
  showRoutes: boolean;
  showNetwork: boolean;
  showSearchPanel: boolean;
  flightFilter: FlightFilter;
  mapStyle: MapStyle;

  setShowAdsb: (value: boolean) => void;
  setShowRoutes: (value: boolean) => void;
  setShowNetwork: (value: boolean) => void;
  setShowSearchPanel: (value: boolean) => void;
  setFlightFilter: (value: FlightFilter) => void;
  setMapStyle: (value: MapStyle) => void;
}

export const useWorldMapSettingsStore = create<WorldMapSettingsState>()(
  persist(
    (set) => ({
      showAdsb: false,
      showRoutes: true,
      showNetwork: false,
      showSearchPanel: false,
      flightFilter: "all",
      mapStyle: "satellite",
      setShowAdsb: (value) => set({ showAdsb: value }),
      setShowRoutes: (value) => set({ showRoutes: value }),
      setShowNetwork: (value) => set({ showNetwork: value }),
      setShowSearchPanel: (value) => set({ showSearchPanel: value }),
      setFlightFilter: (value) => set({ flightFilter: value }),
      setMapStyle: (value) => set({ mapStyle: value }),
    }),
    {
      name: "art-worldmap-settings",
      storage: createJSONStorage(() => localStorage),
      version: 1,
    },
  ),
);
