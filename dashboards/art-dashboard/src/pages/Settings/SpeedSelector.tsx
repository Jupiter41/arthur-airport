import { SPEEDS } from "./types";

export function SpeedSelector({
  current,
  onChange,
}: {
  current: number;
  onChange: (s: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm text-gray-300">Speed</span>
      <div className="flex gap-1">
        {SPEEDS.map((s) => (
          <button
            key={s}
            onClick={() => onChange(s)}
            className={`px-2 py-1 text-xs rounded font-mono transition-colors ${
              current === s
                ? "bg-blue-500 text-white"
                : "bg-gray-700 text-gray-400 hover:bg-gray-600"
            }`}
          >
            {s >= 3600 ? `${s / 3600}h` : s >= 60 ? `${s}×` : `${s}×`}
          </button>
        ))}
      </div>
    </div>
  );
}
