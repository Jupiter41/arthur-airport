import type { AnalysisRecommendation } from "../../types";

const number = (value: number | undefined) => value == null || !Number.isFinite(value) ? "Unavailable" : value.toLocaleString(undefined, { maximumFractionDigits: 2 });

export function RecommendationExplanation({ recommendation, alternatives = [] }: {
  recommendation: AnalysisRecommendation; alternatives?: AnalysisRecommendation[];
}) {
  const r = recommendation;
  const confidence = Math.min(1, r.confidence_score * (r.calibration_confidence_factor ?? 1));
  const samples = r.calibration_samples ?? 0;
  return <section className="rounded-xl border border-sky-400/20 bg-sky-400/5 p-4 space-y-3" aria-label="Recommendation reasoning">
    <div className="flex justify-between gap-3"><h3 className="text-sm">Why this recommendation?</h3><span className="text-xs text-sky-300">Rank #{r.priority_rank}</span></div>
    <p className="text-sm text-gray-300">{r.expected_impact}</p>
    <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
      {[["Impact", number(r.impact_value)], ["Calibrated confidence", `${(confidence * 100).toFixed(0)}%`], ["Cost", number(r.cost_value)], ["Priority score", number(r.priority_score)]].map(([label, value]) => <div key={label}><dt className="text-gray-400">{label}</dt><dd className="font-mono text-sm mt-1 text-sky-100">{value}</dd></div>)}
    </dl>
    <p className="text-xs text-gray-400">Score = impact × calibrated confidence ÷ cost. Impact is a synthetic passenger-minute equivalent; cost is a disruption-minute equivalent. These are not euros.</p>
    <p className="text-xs text-gray-400">Impact factor ×{number(r.calibration_impact_factor ?? 1)} · confidence factor ×{number(r.calibration_confidence_factor ?? 1)} · {samples} eligible outcomes. {samples < 20 ? "Empirical accuracy unvalidated: fewer than 20 samples." : "Sample count alone does not certify accuracy; consult replay validation."}</p>
    {r.effect_status && r.effect_status !== "modelled" && <p className="text-xs text-amber-300">Projection: {r.effect_status.replace(/_/g, " ")}. No executable benefit is implied.</p>}
    <details className="text-xs text-gray-400"><summary className="cursor-pointer text-sky-300">Compare the recorded alternatives</summary>
      <div className="overflow-x-auto mt-2"><table className="w-full text-left"><thead><tr><th className="p-2">Recommendation</th><th className="p-2">Score</th><th className="p-2">Availability</th></tr></thead><tbody>
        {alternatives.map(item => <tr key={item.id} className="border-t border-panel-border"><td className="p-2">#{item.priority_rank} {item.description}</td><td className="p-2 font-mono">{number(item.priority_score)}</td><td className="p-2">{item.executable ? "Executable" : "Advisory"}</td></tr>)}
        {!alternatives.length && <tr><td colSpan={3} className="p-2">No alternative snapshot retained.</td></tr>}
      </tbody></table></div>
    </details>
  </section>;
}
