import { useEffect } from "react";
import { useWeatherStore } from "../stores/weatherStore";
import { weatherApi } from "../hooks/useApi";
import type { WeatherState } from "../types";

const CATEGORY_COLORS: Record<string, string> = {
  CAVOK: "bg-green-600",
  VMC: "bg-teal-600",
  IMC: "bg-amber-600",
  LIFR: "bg-red-600 animate-pulse",
};

export function WeatherStrip() {
  const weather = useWeatherStore((s) => s.current);

  // Bootstrap: if no WS event has arrived yet, fetch once from REST
  useEffect(() => {
    if (!weather) {
      weatherApi
        .current()
        .then((data) => {
          if (data && !useWeatherStore.getState().current) {
            useWeatherStore.getState().setCurrent(data as WeatherState);
          }
        })
        .catch(() => {});
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!weather) {
    return (
      <div className="text-sm text-gray-500 font-mono">Weather: loading...</div>
    );
  }

  const cat = weather.category;
  const badgeClass = CATEGORY_COLORS[cat] ?? "bg-gray-600";

  const windStr = `${weather.wind_direction_deg.toString().padStart(3, "0")}${weather.wind_speed_kt.toString().padStart(2, "0")}${weather.wind_gust_kt ? `G${weather.wind_gust_kt}` : ""}KT`;

  return (
    <div className="flex items-center gap-2 text-sm font-mono text-gray-300">
      <span
        className={`${badgeClass} text-white text-xs px-2 py-0.5 rounded font-bold`}
      >
        {cat}
      </span>
      <span>{weather.visibility_m}m</span>
      <span>·</span>
      <span>{windStr}</span>
      {weather.cloud_layers.length > 0 && (
        <>
          <span>·</span>
          <span>{weather.cloud_layers.join(" ")}</span>
        </>
      )}
      <span>·</span>
      <span>{weather.temperature_c}°C</span>
      <span>·</span>
      <span>Q{weather.pressure_hpa}</span>
    </div>
  );
}
