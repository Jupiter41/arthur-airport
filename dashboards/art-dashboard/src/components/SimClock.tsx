import { useSimStore } from "../stores/simStore";
import { parseSimTime } from "../utils/simTime";

export function SimClock() {
  const { sim_time, day_number, paused, speed_multiplier, tick_count } =
    useSimStore((s) => s.status);

  const t = parseSimTime(sim_time);
  const hh = t.getUTCHours().toString().padStart(2, "0");
  const mm = t.getUTCMinutes().toString().padStart(2, "0");

  return (
    <div className="flex items-center gap-2 text-sm font-mono">
      <span className="text-gray-400">Simulated</span>
      <span className="text-white font-bold">
        {tick_count > 0 && Number.isFinite(t.getTime())
          ? `Day ${day_number} · ${hh}:${mm} UTC`
          : "Awaiting source clock"}
      </span>
      <span className="text-gray-400">{speed_multiplier}×</span>
      {paused && (
        <span className="bg-amber-600 text-white text-xs px-1.5 py-0.5 rounded font-bold">
          PAUSED
        </span>
      )}
      {!paused && <span className="text-gray-400 text-xs">Running</span>}
    </div>
  );
}
