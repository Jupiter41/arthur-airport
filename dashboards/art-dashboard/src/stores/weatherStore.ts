import { create } from "zustand";
import type { WeatherState } from "../types";

interface WeatherStoreState {
  current: WeatherState | null;
  setCurrent: (w: WeatherState) => void;
  updateFromEvent: (payload: Record<string, unknown>) => void;
}

export const useWeatherStore = create<WeatherStoreState>((set) => ({
  current: null,
  setCurrent: (w) => set({ current: w }),
  updateFromEvent: (payload) => {
    const impact = (payload.runway_impact ?? {}) as Record<string, unknown>;

    set({
      current: {
        category: (payload.new_category ??
          payload.category ??
          "VMC") as WeatherState["category"],
        visibility_m: (payload.visibility_m as number) ?? 9999,
        wind_speed_kt: (payload.wind_speed_kt as number) ?? 5,
        wind_direction_deg:
          (payload.wind_direction_deg as number) ??
          (payload.wind_direction as number) ??
          90,
        wind_gust_kt: (payload.wind_gust_kt as number | null) ?? null,
        temperature_c: (payload.temperature_c as number) ?? 15,
        dewpoint_c:
          (payload.dewpoint_c as number) ??
          (payload.dew_point_c as number) ??
          10,
        pressure_hpa:
          (payload.pressure_hpa as number) ??
          (payload.qnh_hpa as number) ??
          1013,
        ceiling_ft: (payload.ceiling_ft as number | null) ?? null,
        cloud_layers: (payload.cloud_layers as string[]) ?? [],
        phenomena: (payload.phenomena as string[]) ?? [],
        metar_raw: (payload.metar_raw as string) ?? "",
        runway_impact:
          (impact.category as string) ??
          (payload.runway_impact as string) ??
          "normal",
        arrival_rate:
          (payload.arrival_rate as number) ??
          (impact.arrival_rate as number) ??
          32,
        departure_rate:
          (payload.departure_rate as number) ??
          (impact.departure_rate as number) ??
          32,
        sim_time: (payload.sim_time as string) ?? "",
      },
    });
  },
}));
