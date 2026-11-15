import { useState } from "react";
import {
  airportApi,
  flightsApi,
  weatherApi,
  incidentsApi,
  passengersApi,
  baggageApi,
} from "../hooks/useApi";
import { exportRaw } from "../utils/exportData";

export function SnapshotExport() {
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  async function download() {
    setBusy(true);
    setMessage("");
    const names = [
      "airport",
      "flights",
      "weather",
      "incidents",
      "passengers",
      "baggage",
    ];
    try {
      const values = await Promise.allSettled([
        airportApi.snapshot(),
        flightsApi.list({ limit: "500" }),
        weatherApi.current(),
        incidentsApi.list({ limit: "100" }),
        passengersApi.summary(),
        baggageApi.summary(),
      ]);
      const unavailable = values.flatMap((value, i) =>
        value.status === "rejected" ? [names[i]] : [],
      );
      exportRaw(
        {
          exported_at: new Date().toISOString(),
          unavailable,
          ...Object.fromEntries(
            values.map((value, i) => [
              names[i],
              value.status === "fulfilled" ? value.value : null,
            ]),
          ),
        },
        "airport-snapshot",
      );
      setMessage(
        unavailable.length
          ? `Exported a partial snapshot. Unavailable: ${unavailable.join(", ")}.`
          : "Snapshot exported. Flight and incident lists use the displayed API limits.",
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card space-y-3">
      <h2>Export observations</h2>
      <p className="text-sm text-gray-400">
        Download a JSON snapshot of current observations. Unavailable domains
        are labelled in the export.
      </p>
      <button
        className="btn-secondary"
        disabled={busy}
        onClick={() => void download()}
      >
        {busy ? "Exporting…" : "Export airport snapshot"}
      </button>
      {message && (
        <p role="status" className="text-sm">
          {message}
        </p>
      )}
    </section>
  );
}
