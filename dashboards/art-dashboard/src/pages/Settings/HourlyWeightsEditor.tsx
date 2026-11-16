import { DEFAULT_HOURS } from "./types";

export function HourlyWeightsEditor({
  weights,
  onChange,
}: {
  weights: Record<string, number>;
  onChange: (w: Record<string, number>) => void;
}) {
  const maxWeight = Math.max(
    1,
    ...DEFAULT_HOURS.map((h) => weights[String(h)] ?? 0),
  );

  return (
    <div className="overflow-x-auto">
      <p className="text-[10px] text-gray-500 mb-2">
        Drag bars to adjust departure distribution. Higher = more flights.
      </p>
      <div className="flex gap-[2px] h-24 min-w-[540px]">
        {DEFAULT_HOURS.map((h) => {
          const w = weights[String(h)] ?? 0;
          const pct = maxWeight > 0 ? (w / maxWeight) * 100 : 0;
          const isPeak = w >= maxWeight * 0.7;
          return (
            <div key={h} className="relative flex-1 flex flex-col justify-end items-center">
              <input
                type="range"
                aria-label={`Departure weight at ${String(h).padStart(2, "0")}:00`}
                min={0}
                max={20}
                value={w}
                onChange={(e) => {
                  const newWeights = {
                    ...weights,
                    [String(h)]: Number(e.target.value),
                  };
                  onChange(newWeights);
                }}
                className="sr-only peer left-0 top-0"
                id={`hw-${h}`}
              />
              <label
                htmlFor={`hw-${h}`}
                className={`w-full min-h-6 cursor-pointer rounded-t peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-accent transition-all duration-200 ${
                  isPeak
                    ? "bg-blue-500 hover:bg-blue-400"
                    : "bg-gray-600 hover:bg-gray-500"
                }`}
                style={{ height: `${Math.max(pct, 4)}%` }}
                title={`${String(h).padStart(2, "0")}:00 — weight: ${w}`}
                onClick={() => {
                  const next = (w + 1) % 21;
                  onChange({ ...weights, [String(h)]: next });
                }}
                onWheel={(e) => {
                  e.preventDefault();
                  const delta = e.deltaY < 0 ? 1 : -1;
                  const next = Math.max(0, Math.min(20, w + delta));
                  onChange({ ...weights, [String(h)]: next });
                }}
              />
              <span className="text-[8px] text-gray-500 mt-0.5 leading-none">
                {String(h).padStart(2, "0")}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
