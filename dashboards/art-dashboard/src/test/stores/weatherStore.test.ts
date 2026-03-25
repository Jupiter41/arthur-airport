import { describe, it, expect, beforeEach } from "vitest";
import { useWeatherStore } from "../../stores/weatherStore";

describe("weatherStore", () => {
  beforeEach(() => {
    useWeatherStore.setState({ current: null });
  });

  it("setCurrent sets weather state", () => {
    const wx = {
      category: "VMC" as const,
      visibility_m: 9999,
      wind_speed_kt: 10,
      wind_direction_deg: 270,
      wind_gust_kt: null,
      temperature_c: 22,
      dewpoint_c: 14,
      pressure_hpa: 1013,
      ceiling_ft: null,
      cloud_layers: [],
      phenomena: [],
      metar_raw: "",
      runway_impact: "normal",
      arrival_rate: 32,
      departure_rate: 32,
      sim_time: "2025-01-01T06:00:00Z",
    };
    useWeatherStore.getState().setCurrent(wx);
    expect(useWeatherStore.getState().current).toEqual(wx);
  });

  it("updateFromEvent builds weather from Kafka payload", () => {
    useWeatherStore.getState().updateFromEvent({
      new_category: "IMC",
      visibility_m: 2000,
      wind_speed_kt: 25,
      wind_direction_deg: 180,
      wind_gust_kt: 35,
      temperature_c: 8,
      dewpoint_c: 6,
      pressure_hpa: 1008,
      cloud_layers: ["BKN020"],
      phenomena: ["RA"],
      metar_raw: "KART ...",
      runway_impact: { category: "reduced", arrival_rate: 20, departure_rate: 18 },
      sim_time: "2025-01-01T07:00:00Z",
    });
    const wx = useWeatherStore.getState().current!;
    expect(wx.category).toBe("IMC");
    expect(wx.visibility_m).toBe(2000);
    expect(wx.wind_gust_kt).toBe(35);
    expect(wx.arrival_rate).toBe(20);
    expect(wx.departure_rate).toBe(18);
    expect(wx.runway_impact).toBe("reduced");
  });

  it("updateFromEvent uses fallback field names", () => {
    useWeatherStore.getState().updateFromEvent({
      category: "LIFR",
      wind_direction: 90,
      dew_point_c: 3,
      qnh_hpa: 998,
    });
    const wx = useWeatherStore.getState().current!;
    expect(wx.category).toBe("LIFR");
    expect(wx.wind_direction_deg).toBe(90);
    expect(wx.dewpoint_c).toBe(3);
    expect(wx.pressure_hpa).toBe(998);
  });
});
