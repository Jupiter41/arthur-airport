import { useState, useEffect } from "react";
import { incidentsApi } from "../../hooks/useApi";
import { INCIDENT_TYPES, SEVERITY_OPTIONS, LOCATIONS, EXPECTED_EFFECTS } from "./constants";

export function InjectModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [type, setType] = useState<string>("runway_incursion");
  const [severity, setSeverity] = useState<string>("critical");
  const [location, setLocation] = useState<string>("");
  const [preview, setPreview] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const locs = LOCATIONS[type];
    if (locs?.length) setLocation(locs[0]);
  }, [type]);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await incidentsApi.inject({ type, severity, location });
      onClose();
      setPreview(false);
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div
        className="bg-gray-800 rounded-lg shadow-2xl w-[500px] max-h-[90vh] overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-label="Inject incident"
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-bold text-white">Inject Incident</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {!preview ? (
          <div className="p-4 space-y-4">
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Event Type
              </label>
              <select
                className="w-full bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600"
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                {INCIDENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Severity
              </label>
              <select
                className="w-full bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                {SEVERITY_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Location
              </label>
              <select
                className="w-full bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              >
                {(LOCATIONS[type] ?? []).map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                className="text-sm px-4 py-2 rounded bg-gray-600 text-white hover:bg-gray-500"
                onClick={onClose}
              >
                Cancel
              </button>
              <button
                className="text-sm px-4 py-2 rounded bg-amber-600 text-white hover:bg-amber-500 font-bold"
                onClick={() => setPreview(true)}
              >
                Preview →
              </button>
            </div>
          </div>
        ) : (
          <div className="p-4 space-y-4">
            <div className="bg-gray-900 rounded p-3 text-sm">
              <div className="text-white font-bold mb-2">
                Injecting: {type.replace(/_/g, " ")} ({severity.toUpperCase()})
                on {location}
              </div>
              <div className="text-gray-300 whitespace-pre-line text-xs">
                {EXPECTED_EFFECTS[type] ??
                  "Effects will cascade based on severity and location."}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                className="text-sm px-4 py-2 rounded bg-gray-600 text-white hover:bg-gray-500"
                onClick={() => setPreview(false)}
              >
                ← Back
              </button>
              <button
                className="text-sm px-4 py-2 rounded bg-red-600 text-white hover:bg-red-500 font-bold"
                onClick={handleSubmit}
                disabled={submitting}
              >
                {submitting ? "Injecting..." : "Confirm Inject"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
