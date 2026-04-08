import { useState, useCallback, useRef, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { debugApi, weatherApi, simApi } from "../../hooks/useApi";
import { useFlightStore } from "../../stores/flightStore";

/* ──────── Types ──────── */

interface CypherResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
}

interface KafkaEvent {
  id: string;
  timestamp: string;
  event_type: string;
  topic: string;
  payload: Record<string, unknown>;
}

interface Snapshot {
  snapshot_id: string;
  name: string;
  filename: string;
  created_at: string;
  sim_time: string;
  day_number: number;
  node_count: number;
  relationship_count: number;
  size_kb: number;
}

/* ──────── Tab selector ──────── */

type TabId =
  | "inject"
  | "inspector"
  | "cypher"
  | "kafka"
  | "weather"
  | "snapshots";

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "inject", label: "Entity Injection", icon: "💉" },
  { id: "inspector", label: "Inspector", icon: "🔍" },
  { id: "cypher", label: "Cypher Console", icon: "⌨️" },
  { id: "kafka", label: "Kafka Inspector", icon: "📡" },
  { id: "weather", label: "Weather Source", icon: "🌤️" },
  { id: "snapshots", label: "Snapshots", icon: "📸" },
];

/* ──────── Injection Panel ──────── */

function InjectionPanel() {
  const [tab, setTab] = useState<"passenger" | "flight" | "baggage">(
    "passenger",
  );
  const [flightId, setFlightId] = useState("");
  const [count, setCount] = useState(10);
  const [status, setStatus] = useState("checked_in");
  const [bagZone, setBagZone] = useState("check_in");
  const [result, setResult] = useState<string | null>(null);

  // Flight injection
  const [flightDir, setFlightDir] = useState("departure");
  const [flightDest, setFlightDest] = useState("");
  const [flightGate, setFlightGate] = useState("");
  const [seedPax, setSeedPax] = useState(true);
  const [seedBags, setSeedBags] = useState(true);

  const flights = useFlightStore((s) => s.flights);
  const flightOptions = Object.values(flights).slice(0, 50);

  const paxMutation = useMutation({
    mutationFn: () => debugApi.injectPassengers(flightId, count, status),
    onSuccess: (data) => setResult(JSON.stringify(data, null, 2)),
    onError: (err) => setResult(`Error: ${err.message}`),
  });

  const flightMutation = useMutation({
    mutationFn: () =>
      debugApi.injectFlight({
        direction: flightDir,
        destination: flightDest || undefined,
        gate: flightGate || undefined,
        seed_passengers: seedPax,
        seed_baggage: seedBags,
      }),
    onSuccess: (data) => setResult(JSON.stringify(data, null, 2)),
    onError: (err) => setResult(`Error: ${err.message}`),
  });

  const bagMutation = useMutation({
    mutationFn: () => debugApi.injectBaggage(flightId, count, bagZone),
    onSuccess: (data) => setResult(JSON.stringify(data, null, 2)),
    onError: (err) => setResult(`Error: ${err.message}`),
  });

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {(["passenger", "flight", "baggage"] as const).map((t) => (
          <button
            key={t}
            onClick={() => {
              setTab(t);
              setResult(null);
            }}
            className={`px-3 py-1.5 text-sm rounded capitalize ${
              tab === t
                ? "bg-blue-600 text-white"
                : "bg-gray-700 text-gray-300 hover:bg-gray-600"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "passenger" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Flight</label>
            <select
              className="flex-1 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              value={flightId}
              onChange={(e) => setFlightId(e.target.value)}
            >
              <option value="">Select a flight...</option>
              {flightOptions.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.flight_number} — {f.origin_iata}→{f.destination_iata} (
                  {f.status})
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Count</label>
            <input
              type="number"
              className="w-24 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              value={count}
              min={1}
              max={500}
              onChange={(e) => setCount(Number(e.target.value))}
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Status</label>
            <select
              className="bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              {[
                "booked",
                "checked_in",
                "security_queue",
                "airside",
                "at_gate",
                "boarding",
                "boarded",
              ].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => paxMutation.mutate()}
            disabled={!flightId || paxMutation.isPending}
            className="px-4 py-2 bg-green-600 text-white rounded text-sm font-semibold
                       hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {paxMutation.isPending
              ? "Injecting..."
              : `Inject ${count} Passengers`}
          </button>
        </div>
      )}

      {tab === "flight" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Direction</label>
            <select
              className="bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              value={flightDir}
              onChange={(e) => setFlightDir(e.target.value)}
            >
              <option value="departure">Departure</option>
              <option value="arrival">Arrival</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Destination</label>
            <input
              className="flex-1 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              placeholder="IATA code (e.g. LHR, leave empty for random)"
              value={flightDest}
              onChange={(e) => setFlightDest(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Gate</label>
            <input
              className="flex-1 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              placeholder="e.g. A05 (leave empty for auto)"
              value={flightGate}
              onChange={(e) => setFlightGate(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-gray-400">
              <input
                type="checkbox"
                checked={seedPax}
                onChange={(e) => setSeedPax(e.target.checked)}
              />
              Seed passengers
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-400">
              <input
                type="checkbox"
                checked={seedBags}
                onChange={(e) => setSeedBags(e.target.checked)}
              />
              Seed baggage
            </label>
          </div>
          <button
            onClick={() => flightMutation.mutate()}
            disabled={flightMutation.isPending}
            className="px-4 py-2 bg-green-600 text-white rounded text-sm font-semibold
                       hover:bg-green-500 disabled:opacity-40"
          >
            {flightMutation.isPending ? "Creating..." : "Create Flight"}
          </button>
        </div>
      )}

      {tab === "baggage" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Flight</label>
            <select
              className="flex-1 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              value={flightId}
              onChange={(e) => setFlightId(e.target.value)}
            >
              <option value="">Select a flight...</option>
              {flightOptions.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.flight_number} — {f.origin_iata}→{f.destination_iata}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Count</label>
            <input
              type="number"
              className="w-24 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              value={count}
              min={1}
              max={200}
              onChange={(e) => setCount(Number(e.target.value))}
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400 w-24">Zone</label>
            <select
              className="bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
              value={bagZone}
              onChange={(e) => setBagZone(e.target.value)}
            >
              {[
                "check_in",
                "induction",
                "screening",
                "sorting",
                "make_up",
                "loaded",
              ].map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => bagMutation.mutate()}
            disabled={!flightId || bagMutation.isPending}
            className="px-4 py-2 bg-green-600 text-white rounded text-sm font-semibold
                       hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {bagMutation.isPending ? "Injecting..." : `Inject ${count} Bags`}
          </button>
        </div>
      )}

      {result && (
        <pre className="bg-gray-900 text-green-400 text-xs p-3 rounded overflow-auto max-h-48 font-mono">
          {result}
        </pre>
      )}
    </div>
  );
}

/* ──────── Entity Inspector ──────── */

function EntityInspector() {
  const [label, setLabel] = useState("Flight");
  const [entityId, setEntityId] = useState("");
  const [entity, setEntity] = useState<Record<string, unknown> | null>(null);
  const [editProps, setEditProps] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);

  const fetchMutation = useMutation({
    mutationFn: () => debugApi.getEntity(label, entityId),
    onSuccess: (data) => {
      const d = data as Record<string, unknown>;
      setEntity(d);
      setEditProps(d.properties as Record<string, unknown>);
      setError(null);
    },
    onError: (err) => {
      setError(err.message);
      setEntity(null);
    },
  });

  const updateMutation = useMutation({
    mutationFn: () => debugApi.updateEntity(label, entityId, editProps),
    onSuccess: () => fetchMutation.mutate(),
    onError: (err) => setError(err.message),
  });

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <select
          className="bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        >
          {[
            "Flight",
            "Passenger",
            "Baggage",
            "Gate",
            "Runway",
            "Incident",
            "WeatherState",
          ].map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <input
          className="flex-1 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
          placeholder="Entity ID or tag..."
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
        />
        <button
          onClick={() => fetchMutation.mutate()}
          disabled={!entityId || fetchMutation.isPending}
          className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm
                     hover:bg-blue-500 disabled:opacity-40"
        >
          {fetchMutation.isPending ? "..." : "Fetch"}
        </button>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {entity && (
        <div className="space-y-3">
          <div className="text-xs text-gray-400">
            Labels: {((entity.labels ?? []) as string[]).join(", ")}
          </div>

          <div className="bg-gray-900 rounded p-3 space-y-2 max-h-64 overflow-y-auto">
            {Object.entries(editProps).map(([key, val]) => (
              <div key={key} className="flex items-center gap-2">
                <span className="text-xs text-gray-400 w-36 font-mono truncate">
                  {key}
                </span>
                <input
                  className="flex-1 bg-gray-700 text-white text-xs rounded px-2 py-1 border border-gray-600 font-mono"
                  value={String(val ?? "")}
                  onChange={(e) =>
                    setEditProps((prev) => ({ ...prev, [key]: e.target.value }))
                  }
                />
              </div>
            ))}
          </div>

          <button
            onClick={() => updateMutation.mutate()}
            disabled={updateMutation.isPending}
            className="px-4 py-1.5 bg-amber-600 text-white rounded text-sm
                       hover:bg-amber-500 disabled:opacity-40"
          >
            {updateMutation.isPending ? "Saving..." : "Save Changes"}
          </button>

          {/* Relationships */}
          {Array.isArray(entity.relationships) &&
            (entity.relationships as Record<string, unknown>[]).length > 0 && (
              <div>
                <h4 className="text-xs text-gray-400 font-semibold mt-2 mb-1">
                  Relationships
                </h4>
                <div className="space-y-1 max-h-32 overflow-y-auto">
                  {(entity.relationships as Record<string, unknown>[]).map(
                    (r, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-xs text-gray-400"
                      >
                        <span
                          className={
                            r.direction === "outgoing"
                              ? "text-blue-400"
                              : "text-green-400"
                          }
                        >
                          {r.direction === "outgoing" ? "→" : "←"}
                        </span>
                        <span className="font-mono text-gray-300">
                          {String(r.type)}
                        </span>
                        <span className="text-gray-400">
                          {(r.target_labels as string[])?.join(":")} (
                          {String(r.target_id)})
                        </span>
                      </div>
                    ),
                  )}
                </div>
              </div>
            )}
        </div>
      )}
    </div>
  );
}

/* ──────── Cypher Console ──────── */

function CypherConsole() {
  const [query, setQuery] = useState(
    "MATCH (f:Flight) RETURN f.flight_number, f.status LIMIT 10",
  );
  const [result, setResult] = useState<CypherResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const mutation = useMutation({
    mutationFn: () => debugApi.cypher(query),
    onSuccess: (data) => {
      setResult(data);
      setError(null);
    },
    onError: (err) => {
      setError(err.message);
      setResult(null);
    },
  });

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        mutation.mutate();
      }
    },
    [mutation],
  );

  return (
    <div className="space-y-3">
      <textarea
        ref={textareaRef}
        className="w-full h-32 bg-gray-900 text-green-400 text-sm font-mono rounded p-3
                   border border-gray-600 focus:border-blue-400 focus:outline-none resize-y"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="MATCH (n) RETURN n LIMIT 10"
        spellCheck={false}
      />
      <div className="flex items-center gap-2">
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !query.trim()}
          className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-semibold
                     hover:bg-blue-500 disabled:opacity-40"
        >
          {mutation.isPending ? "Running..." : "Execute (Ctrl+Enter)"}
        </button>
        <span className="text-xs text-gray-400">Read-only queries only</span>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {result && (
        <div className="overflow-auto max-h-80">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-gray-700">
                {result.columns.map((col) => (
                  <th
                    key={col}
                    className="text-left p-2 text-gray-400 font-semibold"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-gray-800 hover:bg-gray-800/50"
                >
                  {result.columns.map((col) => (
                    <td
                      key={col}
                      className="p-2 text-gray-300 max-w-xs truncate"
                    >
                      {JSON.stringify(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-gray-400 mt-2">
            {result.row_count} rows returned
          </p>
        </div>
      )}
    </div>
  );
}

/* ──────── Kafka Event Inspector ──────── */

function KafkaInspector() {
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

function inferTopic(eventType: string): string {
  if (eventType.startsWith("Flight")) return "flights.events";
  if (eventType.startsWith("Passenger")) return "passengers.events";
  if (eventType.startsWith("Baggage")) return "baggage.events";
  if (eventType.startsWith("Weather") || eventType.startsWith("METAR"))
    return "weather.events";
  if (eventType.startsWith("Incident")) return "incidents.events";
  if (eventType.startsWith("Sim") || eventType.startsWith("Snapshot"))
    return "sim.clock";
  return "unknown";
}

/* ──────── Weather Source Panel ──────── */

function WeatherSourcePanel() {
  const [source, setSource] = useState("simulated");
  const [csvPath, setCsvPath] = useState("");
  const [liveIcao, setLiveIcao] = useState("EGLL");
  const [result, setResult] = useState<string | null>(null);

  // Override state
  const [overrides, setOverrides] = useState<Record<string, number | null>>({
    visibility_m: null,
    wind_speed_kt: null,
    ceiling_ft: null,
    temperature_c: null,
  });

  const { data: currentSource } = useQuery({
    queryKey: ["weather-source"],
    queryFn: () => weatherApi.source(),
    refetchInterval: 10000,
  });

  const switchMutation = useMutation({
    mutationFn: () =>
      weatherApi.switchSource(
        source,
        csvPath || undefined,
        liveIcao || undefined,
      ),
    onSuccess: (data) => setResult(JSON.stringify(data, null, 2)),
    onError: (err) => setResult(`Error: ${(err as Error).message}`),
  });

  const overrideMutation = useMutation({
    mutationFn: () => weatherApi.setOverrides(overrides),
    onSuccess: (data) => setResult(JSON.stringify(data, null, 2)),
    onError: (err) => setResult(`Error: ${(err as Error).message}`),
  });

  return (
    <div className="space-y-4">
      {/* Current source */}
      <div className="bg-gray-900 rounded p-3">
        <h4 className="text-xs text-gray-400 font-semibold mb-1">
          Current Source
        </h4>
        <pre className="text-xs text-green-400 font-mono">
          {currentSource
            ? JSON.stringify(currentSource, null, 2)
            : "Loading..."}
        </pre>
      </div>

      {/* Source switcher */}
      <div className="space-y-3">
        <h4 className="text-sm text-gray-400 font-semibold">
          Switch Weather Source
        </h4>
        <div className="flex items-center gap-2">
          <select
            className="bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="simulated">Simulated (FSM)</option>
            <option value="historical">Historical (CSV replay)</option>
            <option value="live">Live (ADDS API)</option>
          </select>
        </div>

        {source === "historical" && (
          <input
            className="w-full bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
            placeholder="CSV path (e.g. /app/data/weather/EGLL_30days.csv)"
            value={csvPath}
            onChange={(e) => setCsvPath(e.target.value)}
          />
        )}

        {source === "live" && (
          <input
            className="w-full bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
            placeholder="ICAO station (e.g. EGLL, LFPG)"
            value={liveIcao}
            onChange={(e) => setLiveIcao(e.target.value)}
          />
        )}

        <button
          onClick={() => switchMutation.mutate()}
          disabled={switchMutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-semibold
                     hover:bg-blue-500 disabled:opacity-40"
        >
          {switchMutation.isPending ? "Switching..." : "Switch Source"}
        </button>
      </div>

      {/* Parameter overrides */}
      <div className="space-y-3">
        <h4 className="text-sm text-gray-400 font-semibold">
          Parameter Overrides
        </h4>
        <p className="text-xs text-gray-400">
          Lock individual parameters regardless of active source. Leave empty to
          unlock.
        </p>

        {(
          [
            "visibility_m",
            "wind_speed_kt",
            "ceiling_ft",
            "temperature_c",
          ] as const
        ).map((key) => (
          <div key={key} className="flex items-center gap-2">
            <label className="text-xs text-gray-400 w-28 font-mono">
              {key}
            </label>
            <input
              type="number"
              className="w-28 bg-gray-700 text-white text-sm rounded px-2 py-1 border border-gray-600"
              placeholder="unlocked"
              value={overrides[key] ?? ""}
              onChange={(e) =>
                setOverrides((prev) => ({
                  ...prev,
                  [key]: e.target.value === "" ? null : Number(e.target.value),
                }))
              }
            />
          </div>
        ))}

        <button
          onClick={() => overrideMutation.mutate()}
          disabled={overrideMutation.isPending}
          className="px-4 py-2 bg-amber-600 text-white rounded text-sm font-semibold
                     hover:bg-amber-500 disabled:opacity-40"
        >
          {overrideMutation.isPending ? "Applying..." : "Apply Overrides"}
        </button>
      </div>

      {result && (
        <pre className="bg-gray-900 text-green-400 text-xs p-3 rounded overflow-auto max-h-32 font-mono">
          {result}
        </pre>
      )}
    </div>
  );
}

/* ──────── Snapshots Panel ──────── */

function SnapshotsPanel() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const { data: snapshotsData, isLoading } = useQuery({
    queryKey: ["snapshots"],
    queryFn: () => debugApi.listSnapshots(),
    refetchInterval: 15000,
  });

  const snapshots = (snapshotsData?.snapshots ?? []) as Snapshot[];

  const createMutation = useMutation({
    mutationFn: () => debugApi.createSnapshot(name),
    onSuccess: (data) => {
      setStatus(`Created: ${JSON.stringify(data)}`);
      setName("");
      queryClient.invalidateQueries({ queryKey: ["snapshots"] });
    },
    onError: (err) => setStatus(`Error: ${err.message}`),
  });

  const restoreMutation = useMutation({
    mutationFn: (filename: string) => debugApi.restoreSnapshot(filename),
    onSuccess: (data) => setStatus(`Restored: ${JSON.stringify(data)}`),
    onError: (err) => setStatus(`Error: ${err.message}`),
  });

  const deleteMutation = useMutation({
    mutationFn: (filename: string) => debugApi.deleteSnapshot(filename),
    onSuccess: () => {
      setStatus("Deleted");
      queryClient.invalidateQueries({ queryKey: ["snapshots"] });
    },
    onError: (err) => setStatus(`Error: ${err.message}`),
  });

  return (
    <div className="space-y-4">
      {/* Create snapshot */}
      <div className="flex gap-2">
        <input
          className="flex-1 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
          placeholder="Snapshot name (e.g. morning-peak)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          onClick={() => createMutation.mutate()}
          disabled={!name.trim() || createMutation.isPending}
          className="px-4 py-1.5 bg-green-600 text-white rounded text-sm font-semibold
                     hover:bg-green-500 disabled:opacity-40"
        >
          {createMutation.isPending ? "Saving..." : "Save Snapshot"}
        </button>
      </div>

      {/* Snapshot list */}
      {isLoading ? (
        <p className="text-sm text-gray-400">Loading snapshots...</p>
      ) : snapshots.length === 0 ? (
        <p className="text-sm text-gray-400">No snapshots saved yet</p>
      ) : (
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {snapshots.map((snap) => (
            <div
              key={snap.snapshot_id}
              className="bg-gray-900 rounded p-3 border border-gray-800"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-white font-semibold">
                  {snap.name}
                </span>
                <span className="text-xs text-gray-400">{snap.size_kb} KB</span>
              </div>
              <div className="text-xs text-gray-400 space-y-0.5">
                <div>Sim time: {new Date(snap.sim_time).toLocaleString()}</div>
                <div>
                  Day {snap.day_number} — {snap.node_count} nodes,{" "}
                  {snap.relationship_count} rels
                </div>
                <div>Created: {new Date(snap.created_at).toLocaleString()}</div>
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => restoreMutation.mutate(snap.filename)}
                  disabled={restoreMutation.isPending}
                  className="px-3 py-1 bg-blue-600 text-white rounded text-xs
                             hover:bg-blue-500 disabled:opacity-40"
                >
                  Restore
                </button>
                <button
                  onClick={() => deleteMutation.mutate(snap.filename)}
                  disabled={deleteMutation.isPending}
                  className="px-3 py-1 bg-red-600 text-white rounded text-xs
                             hover:bg-red-500 disabled:opacity-40"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {status && (
        <pre className="bg-gray-900 text-green-400 text-xs p-3 rounded overflow-auto max-h-24 font-mono">
          {status}
        </pre>
      )}
    </div>
  );
}

/* ──────── Weather History Chart ──────── */

const CATEGORY_COLORS: Record<string, string> = {
  CAVOK: "#22c55e",
  VMC: "#3b82f6",
  IMC: "#f59e0b",
  LIFR: "#ef4444",
};

function WeatherHistoryChart() {
  const { data } = useQuery({
    queryKey: ["weather-history"],
    queryFn: () => weatherApi.history(12),
    refetchInterval: 30000,
  });

  const states =
    (
      data as {
        states?: {
          category: string;
          from: string;
          to: string;
          duration_minutes: number;
        }[];
      }
    )?.states ?? [];

  if (states.length === 0) {
    return (
      <p className="text-xs text-gray-400">No weather history available</p>
    );
  }

  const totalMinutes =
    states.reduce((sum, s) => sum + s.duration_minutes, 0) || 720;

  return (
    <div className="space-y-1">
      <h4 className="text-xs text-gray-400 font-semibold">
        12h Weather History
      </h4>
      <div className="flex h-6 rounded overflow-hidden">
        {states.map((s, i) => {
          const widthPct = Math.max(
            1,
            (s.duration_minutes / totalMinutes) * 100,
          );
          return (
            <div
              key={i}
              className="relative group"
              style={{
                width: `${widthPct}%`,
                backgroundColor: CATEGORY_COLORS[s.category] ?? "#6b7280",
              }}
              title={`${s.category} — ${s.duration_minutes}min`}
            >
              {widthPct > 8 && (
                <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-white/80">
                  {s.category}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-gray-400">
        <span>
          {states[0]?.from ? new Date(states[0].from).toLocaleTimeString() : ""}
        </span>
        <span>
          {states[states.length - 1]?.to
            ? new Date(states[states.length - 1].to).toLocaleTimeString()
            : ""}
        </span>
      </div>
    </div>
  );
}

/* ──────── Main Debug Page ──────── */

export default function DebugPage() {
  const [activeTab, setActiveTab] = useState<TabId>("inject");

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          🛠️ Debug Panel
        </h1>
        <span className="text-xs text-gray-400 bg-gray-800 px-2 py-1 rounded font-mono">
          Ctrl+D to toggle
        </span>
      </div>

      {/* Weather history sparkline at top */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-3">
        <WeatherHistoryChart />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-800 p-1 rounded-lg">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 text-sm rounded transition-colors ${
              activeTab === tab.id
                ? "bg-gray-700 text-white font-semibold"
                : "text-gray-400 hover:text-gray-300 hover:bg-gray-700/50"
            }`}
          >
            <span>{tab.icon}</span>
            <span className="hidden lg:inline">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        {activeTab === "inject" && <InjectionPanel />}
        {activeTab === "inspector" && <EntityInspector />}
        {activeTab === "cypher" && <CypherConsole />}
        {activeTab === "kafka" && <KafkaInspector />}
        {activeTab === "weather" && <WeatherSourcePanel />}
        {activeTab === "snapshots" && <SnapshotsPanel />}
      </div>
    </div>
  );
}

export { WeatherHistoryChart };
