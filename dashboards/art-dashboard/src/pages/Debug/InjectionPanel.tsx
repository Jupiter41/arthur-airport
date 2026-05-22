import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { debugApi } from "../../hooks/useApi";
import { useFlightStore } from "../../stores/flightStore";

export function InjectionPanel() {
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
