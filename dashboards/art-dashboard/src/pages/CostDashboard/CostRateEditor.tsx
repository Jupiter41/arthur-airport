import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { costsApi } from "../../hooks/useApi";
import { COST_PRESETS, EDITABLE_CATEGORIES } from "./constants";

export function CostRateModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"preset" | "custom">("preset");
  const [customEdits, setCustomEdits] = useState<
    Record<string, Record<string, number>>
  >({});
  const [feedback, setFeedback] = useState<string | null>(null);

  const { data: currentRates, isLoading } = useQuery({
    queryKey: ["costs", "rates"],
    queryFn: () => costsApi.rates(),
  });

  const mutation = useMutation({
    mutationFn: (overrides: Record<string, unknown>) =>
      costsApi.patchRates(overrides),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["costs"] });
      setFeedback("✓ Rates updated — new costs will use the updated rates.");
      setTimeout(() => setFeedback(null), 5000);
    },
    onError: (e) => {
      setFeedback(
        `✗ Failed: ${e instanceof Error ? e.message : "Unknown error"}`,
      );
    },
  });

  const applyPreset = useCallback(
    (presetId: string) => {
      const preset = COST_PRESETS[presetId];
      if (preset) mutation.mutate(preset.overrides);
    },
    [mutation],
  );

  const applyCustom = useCallback(() => {
    if (Object.keys(customEdits).length === 0) return;
    mutation.mutate(customEdits);
    setCustomEdits({});
  }, [customEdits, mutation]);

  const updateField = useCallback(
    (category: string, field: string, value: number) => {
      setCustomEdits((prev) => ({
        ...prev,
        [category]: { ...(prev[category] ?? {}), [field]: value },
      }));
    },
    [],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Cost Rate Configuration"
    >
      <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-3xl max-h-[85vh] overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            ⚙️ Cost Rate Configuration
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white text-xl leading-none px-2 py-1 rounded hover:bg-gray-700 transition-colors"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="space-y-4">
          {/* Mode toggle */}
          <div className="flex gap-2">
            <button
              onClick={() => setMode("preset")}
              className={`text-xs px-3 py-1.5 rounded transition-colors ${
                mode === "preset"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-700 text-gray-400 hover:bg-gray-600"
              }`}
            >
              Preset Profiles
            </button>
            <button
              onClick={() => setMode("custom")}
              className={`text-xs px-3 py-1.5 rounded transition-colors ${
                mode === "custom"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-700 text-gray-400 hover:bg-gray-600"
              }`}
            >
              Custom Editor
            </button>
          </div>

          {/* Preset mode */}
          {mode === "preset" && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {Object.entries(COST_PRESETS).map(([id, preset]) => (
                <div
                  key={id}
                  className="rounded-lg border border-panel-border bg-surface p-3 flex flex-col justify-between"
                >
                  <div>
                    <div className="text-sm font-medium text-white">
                      {preset.label}
                    </div>
                    <div className="text-[10px] text-gray-400 mt-0.5">
                      {preset.description}
                    </div>
                  </div>
                  <button
                    onClick={() => applyPreset(id)}
                    disabled={mutation.isPending}
                    className="mt-2 text-xs px-3 py-1 rounded bg-accent/20 text-accent border border-accent/30 hover:bg-accent/30 transition-colors self-start disabled:opacity-50"
                  >
                    Apply
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Custom mode */}
          {mode === "custom" && (
            <div className="space-y-4">
              {isLoading && (
                <div className="text-xs text-gray-400 py-2">
                  Loading current rates…
                </div>
              )}
              {currentRates && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {EDITABLE_CATEGORIES.map((cat) => {
                    const catRates = currentRates[cat.key] as
                      | Record<string, number>
                      | undefined;
                    return (
                      <div
                        key={cat.key}
                        className="rounded-lg bg-surface border border-panel-border p-3"
                      >
                        <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wide mb-2">
                          {cat.label}
                        </h4>
                        <div className="space-y-2">
                          {cat.fields.map((field) => {
                            const current = catRates?.[field.key] ?? 0;
                            const edited = customEdits[cat.key]?.[field.key];
                            return (
                              <div
                                key={field.key}
                                className="flex items-center justify-between gap-2"
                              >
                                <label className="text-[10px] text-gray-400 flex-1">
                                  {field.label}
                                </label>
                                <input
                                  type="number"
                                  step={field.step}
                                  min={0}
                                  value={edited ?? current}
                                  onChange={(e) =>
                                    updateField(
                                      cat.key,
                                      field.key,
                                      Number(e.target.value),
                                    )
                                  }
                                  className={`w-24 text-right text-xs bg-gray-800 border rounded px-2 py-1 ${
                                    edited !== undefined && edited !== current
                                      ? "border-accent text-accent"
                                      : "border-panel-border text-white"
                                  }`}
                                />
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {Object.keys(customEdits).length > 0 && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={applyCustom}
                    disabled={mutation.isPending}
                    className="text-xs px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    {mutation.isPending ? "Applying…" : "Apply Custom Rates"}
                  </button>
                  <button
                    onClick={() => setCustomEdits({})}
                    className="text-xs px-3 py-2 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
                  >
                    Reset
                  </button>
                  <span className="text-[10px] text-gray-500">
                    {Object.values(customEdits).reduce(
                      (acc, cat) => acc + Object.keys(cat).length,
                      0,
                    )}{" "}
                    field(s) modified
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Feedback */}
          {feedback && (
            <div
              className={`text-xs px-3 py-2 rounded-lg ${
                feedback.startsWith("✓")
                  ? "bg-green-900/30 border border-green-700/40 text-green-300"
                  : "bg-red-900/30 border border-red-700/40 text-red-300"
              }`}
            >
              {feedback}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
