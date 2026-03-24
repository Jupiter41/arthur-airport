import { useSimStore } from "../stores/simStore";

export function SimClock() {
  const { sim_time, day_number, paused, speed_multiplier } = useSimStore(
    (s) => s.status,
  );

  const t = new Date(sim_time);
  const hh = t.getUTCHours().toString().padStart(2, "0");
  const mm = t.getUTCMinutes().toString().padStart(2, "0");

  return (
    <div className="flex items-center gap-2 text-sm font-mono">
      <span className="text-gray-400">SIM:</span>
      <span className="text-white font-bold">
        Day {day_number} · {hh}:{mm}Z
      </span>
      <span className="text-gray-400">{speed_multiplier}×</span>
      {paused && (
        <span className="bg-amber-600 text-white text-xs px-1.5 py-0.5 rounded font-bold animate-pulse">
          PAUSED
        </span>
      )}
      {!paused && <span className="text-green-400 text-xs">▶</span>}
    </div>
  );
}
