import { useState, useCallback } from "react";
import { AutonomousPanel } from "../../components/AutonomousPanel";
import { incidentsApi } from "../../hooks/useApi";

const INCIDENT_TYPES = [
  {
    value: "runway_incursion",
    label: "Runway Incursion",
    severity: "critical",
  },
  { value: "bird_strike", label: "Bird Strike", severity: "high" },
  { value: "medical_emergency", label: "Medical Emergency", severity: "high" },
  { value: "security_breach", label: "Security Breach", severity: "critical" },
  {
    value: "ground_vehicle_collision",
    label: "Ground Vehicle Collision",
    severity: "high",
  },
  { value: "fuel_spill", label: "Fuel Spill", severity: "medium" },
  {
    value: "weather_diversion",
    label: "Weather Diversion",
    severity: "medium",
  },
  { value: "equipment_failure", label: "Equipment Failure", severity: "low" },
];

export function AutonomousModal({ onClose }: { onClose: () => void }) {
  const [incidentType, setIncidentType] = useState(INCIDENT_TYPES[0].value);
  const [severity, setSeverity] = useState("critical");
  const [location, setLocation] = useState("runway-09L");
  const [injecting, setInjecting] = useState(false);
  const [injectResult, setInjectResult] = useState<string | null>(null);

  // Sync severity when type changes
  const handleTypeChange = useCallback((type: string) => {
    setIncidentType(type);
    const found = INCIDENT_TYPES.find((t) => t.value === type);
    if (found) setSeverity(found.severity);
  }, []);

  const handleInject = useCallback(async () => {
    setInjecting(true);
    setInjectResult(null);
    try {
      await incidentsApi.inject({
        type: incidentType,
        severity,
        location,
      });
      setInjectResult(
        `✓ Injected ${incidentType.replace(/_/g, " ")} at ${location}`,
      );
    } catch (e) {
      setInjectResult(
        `✗ Failed: ${e instanceof Error ? e.message : "Unknown error"}`,
      );
    } finally {
      setInjecting(false);
    }
  }, [incidentType, severity, location]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Autonomous Operations"
    >
      <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            🤖 Autonomous Operations
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white text-xl leading-none px-2 py-1 rounded hover:bg-gray-700 transition-colors"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Inject Incident Section */}
        <div className="mb-6 bg-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-bold text-white mb-3">
            🚨 Inject Incident
          </h3>
          <p className="text-[10px] text-gray-400 mb-3">
            Inject a simulated incident to trigger the autonomous recommendation
            pipeline and observe the system&apos;s response.
          </p>

          <div className="grid grid-cols-3 gap-3 mb-3">
            <div>
              <label className="text-[10px] text-gray-400 block mb-1">
                Type
              </label>
              <select
                value={incidentType}
                onChange={(e) => handleTypeChange(e.target.value)}
                className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-white"
              >
                {INCIDENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-400 block mb-1">
                Severity
              </label>
              <select
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-white"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-400 block mb-1">
                Location
              </label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-white"
                placeholder="runway-09L"
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleInject}
              disabled={injecting}
              className="text-xs px-4 py-2 rounded bg-red-600 hover:bg-red-500 text-white transition-colors disabled:opacity-50"
            >
              {injecting ? "Injecting…" : "⚡ Inject Incident"}
            </button>
            {injectResult && (
              <span
                className={`text-xs ${
                  injectResult.startsWith("✓")
                    ? "text-green-400"
                    : "text-red-400"
                }`}
              >
                {injectResult}
              </span>
            )}
          </div>
        </div>

        {/* Autonomous Panel */}
        <AutonomousPanel />
      </div>
    </div>
  );
}
