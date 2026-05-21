import type { WeatherState } from "../../types";

const catColors: Record<string, string> = {
  CAVOK: "bg-green-600",
  VMC: "bg-teal-600",
  IMC: "bg-amber-600",
  LIFR: "bg-red-600",
};

const catDescriptions: Record<string, string> = {
  CAVOK: "Clear skies, visibility >10 km",
  VMC: "Visual conditions, good visibility",
  IMC: "Instrument conditions, reduced visibility",
  LIFR: "Low IFR, very poor visibility",
};

export function WeatherSidePanel({
  weather,
}: {
  weather: WeatherState | null;
}) {
  if (!weather) return null;

  const windDir = weather.wind_direction_deg;

  return (
    <div className="bg-gray-800 rounded p-3 space-y-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">Weather</h3>

      {/* Category badge with description */}
      <div className="flex flex-col items-center gap-1">
        <span
          className={`${catColors[weather.category] ?? "bg-gray-600"} text-white text-lg font-bold px-4 py-2 rounded`}
        >
          {weather.category}
        </span>
        <span className="text-[10px] text-gray-400">
          {catDescriptions[weather.category] ?? "Unknown category"}
        </span>
      </div>

      {/* METAR */}
      <div className="font-mono text-[10px] text-gray-300 bg-gray-900 rounded p-2 break-all">
        {weather.metar_raw}
      </div>

      {/* Wind compass */}
      <div className="flex justify-center">
        <svg width={80} height={80} viewBox="0 0 80 80">
          <circle
            cx={40}
            cy={40}
            r={35}
            className="fill-none stroke-gray-600"
            strokeWidth={1}
          />
          <text
            x={40}
            y={10}
            textAnchor="middle"
            className="fill-gray-500 text-[8px]"
          >
            N
          </text>
          <text
            x={72}
            y={43}
            textAnchor="middle"
            className="fill-gray-500 text-[8px]"
          >
            E
          </text>
          <text
            x={40}
            y={76}
            textAnchor="middle"
            className="fill-gray-500 text-[8px]"
          >
            S
          </text>
          <text
            x={8}
            y={43}
            textAnchor="middle"
            className="fill-gray-500 text-[8px]"
          >
            W
          </text>
          {/* Wind arrow */}
          <g transform={`rotate(${windDir}, 40, 40)`}>
            <line
              x1={40}
              y1={40}
              x2={40}
              y2={12}
              className="stroke-cyan-400"
              strokeWidth={2}
            />
            <polygon points="40,8 36,16 44,16" className="fill-cyan-400" />
          </g>
          <text
            x={40}
            y={44}
            textAnchor="middle"
            className="fill-white text-[9px] font-bold"
          >
            {weather.wind_speed_kt}kt
          </text>
        </svg>
      </div>

      {/* Impact */}
      <div className="text-xs text-gray-300 space-y-1">
        <div className="flex justify-between">
          <span>Visibility</span>
          <span className="text-white font-bold">
            {weather.visibility_m >= 9999
              ? ">10 km"
              : `${(weather.visibility_m / 1000).toFixed(1)} km`}
          </span>
        </div>
        {weather.ceiling_ft != null && (
          <div className="flex justify-between">
            <span>Ceiling</span>
            <span className="text-white font-bold">
              {weather.ceiling_ft} ft
            </span>
          </div>
        )}
        <div className="flex justify-between">
          <span>Arrival rate</span>
          <span className="text-white font-bold">
            {weather.arrival_rate}/hr
          </span>
        </div>
        <div className="flex justify-between">
          <span>Departure rate</span>
          <span className="text-white font-bold">
            {weather.departure_rate}/hr
          </span>
        </div>
      </div>

      {/* Category legend */}
      <div className="border-t border-gray-700 pt-2 space-y-1">
        {(["CAVOK", "VMC", "IMC", "LIFR"] as const).map((cat) => (
          <div key={cat} className="flex items-center gap-2 text-[10px]">
            <span
              className={`inline-block w-2 h-2 rounded-full ${catColors[cat]}`}
            />
            <span
              className={
                cat === weather.category
                  ? "text-white font-bold"
                  : "text-gray-500"
              }
            >
              {cat}
            </span>
            <span className="text-gray-500">{catDescriptions[cat]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
