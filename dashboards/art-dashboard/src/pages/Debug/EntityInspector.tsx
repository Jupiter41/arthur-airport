import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { debugApi } from "../../hooks/useApi";

export function EntityInspector() {
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
