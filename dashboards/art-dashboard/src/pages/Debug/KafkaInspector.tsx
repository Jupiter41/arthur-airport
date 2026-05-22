import { useState, useRef, useEffect } from "react";
import type { KafkaEvent } from "./types";
import { inferTopic } from "./helpers";

export function KafkaInspector() {
  const [events, setEvents] = useState<KafkaEvent[]>([]);
  const [filter, setFilter] = useState("");
  const [paused, setPaused] = useState(false);
  const eventsRef = useRef<KafkaEvent[]>([]);
  const maxEvents = 200;

  // Listen to raw WebSocket events using a custom message handler
  useEffect(() => {
    const handleWsMessage = (e: MessageEvent) => {
      if (paused) return;
      try {
        const data = JSON.parse(e.data);
        if (!data.event_type || data.type === "ping" || data.type === "pong")
          return;

        const event: KafkaEvent = {
          id: data.event_id ?? `${Date.now()}-${Math.random()}`,
          timestamp:
            data.sim_time ?? data.produced_at ?? new Date().toISOString(),
          event_type: data.event_type,
          topic: data.topic ?? inferTopic(data.event_type),
          payload: data.payload ?? data,
        };

        eventsRef.current = [event, ...eventsRef.current].slice(0, maxEvents);
        setEvents([...eventsRef.current]);
      } catch {
        /* ignore parse errors */
      }
    };

    // Find the existing WebSocket on the page
    const ws = document.querySelector("[data-ws]") as unknown;
    if (ws) return;

    // Register a global listener on the window for WS events from useWebSocket
    window.addEventListener(
      "ws-event" as keyof WindowEventMap,
      handleWsMessage as EventListener,
    );
    return () =>
      window.removeEventListener(
        "ws-event" as keyof WindowEventMap,
        handleWsMessage as EventListener,
      );
  }, [paused]);

  const filtered = filter
    ? events.filter(
        (e) =>
          e.event_type.toLowerCase().includes(filter.toLowerCase()) ||
          e.topic.toLowerCase().includes(filter.toLowerCase()),
      )
    : events;

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input
          className="flex-1 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
          placeholder="Filter by event type or topic..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button
          onClick={() => setPaused(!paused)}
          className={`px-3 py-1.5 text-sm rounded ${
            paused ? "bg-green-600 text-white" : "bg-amber-600 text-white"
          }`}
        >
          {paused ? "Resume" : "Pause"}
        </button>
        <button
          onClick={() => {
            eventsRef.current = [];
            setEvents([]);
          }}
          className="px-3 py-1.5 text-sm rounded bg-gray-600 text-gray-300 hover:bg-gray-500"
        >
          Clear
        </button>
      </div>

      <div className="space-y-1 max-h-96 overflow-y-auto">
        {filtered.length === 0 && (
          <p className="text-sm text-gray-400 p-4 text-center">
            {events.length === 0
              ? "Waiting for events..."
              : "No events match filter"}
          </p>
        )}
        {filtered.map((evt) => (
          <details
            key={evt.id}
            className="bg-gray-900 rounded border border-gray-800"
          >
            <summary className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-gray-800/50">
              <span className="text-xs text-gray-400 font-mono w-20 shrink-0">
                {new Date(evt.timestamp).toLocaleTimeString()}
              </span>
              <span className="text-xs font-semibold text-blue-400 w-40 truncate">
                {evt.event_type}
              </span>
              <span className="text-xs text-gray-400">{evt.topic}</span>
            </summary>
            <pre className="text-xs text-green-400 p-3 font-mono overflow-x-auto">
              {JSON.stringify(evt.payload, null, 2)}
            </pre>
          </details>
        ))}
      </div>
    </div>
  );
}
