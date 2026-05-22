import type { TimelineEvent } from "./types";

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return `${d.getUTCHours().toString().padStart(2, "0")}:${d.getUTCMinutes().toString().padStart(2, "0")}`;
}

export function TimelinePanel({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="bg-gray-800 rounded p-4 text-center text-gray-400 text-sm">
        No events to display. Run the simulation to generate history.
      </div>
    );
  }

  const typeColors: Record<string, string> = {
    weather: "border-blue-500",
    incident: "border-red-500",
    flight: "border-green-500",
  };

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Event Timeline (Current Day)
      </h3>
      <div className="space-y-1 max-h-[400px] overflow-y-auto">
        {events.map((evt, i) => (
          <div
            key={i}
            className={`flex gap-3 text-xs border-l-2 ${typeColors[evt.type] ?? "border-gray-600"} pl-3 py-1`}
          >
            <span className="text-gray-400 font-mono whitespace-nowrap w-12">
              {formatTime(evt.time)}
            </span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                evt.type === "incident"
                  ? "bg-red-900/40 text-red-400"
                  : evt.type === "weather"
                    ? "bg-blue-900/40 text-blue-400"
                    : "bg-green-900/40 text-green-400"
              }`}
            >
              {evt.type.toUpperCase()}
            </span>
            <span className="text-gray-300">{evt.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
