import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { analysisApi } from "../../hooks/useApi";
import { useAccess } from "../../hooks/auth";
import type { DecisionTimeline as Timeline } from "../../types/decisions";
import { RecommendationExplanation } from "./RecommendationExplanation";

const labels: Record<string, string> = {
  detected: "Bottleneck detected", predicted: "Impact predicted", ranked: "Recommendation ranked",
  proposed: "Action proposed", approved: "Action authorized", dispatch_prediction: "Dispatch-time prediction",
  dispatched: "Command queued for dispatch", executed: "Owner confirmed execution", rejected: "Proposal rejected",
  failed: "Action failed", measured: "Outcome measured", awaiting_measurement: "Awaiting outcome measurement",
};
export const decisionLabel = (value: string) => labels[value] ?? value.replace(/_/g, " ");
const amount = (value: number | undefined) => value == null ? "Unavailable" : value.toFixed(2);
export function simTimestamp(value: string | null) {
  // ISO simulation time is shown as stored, without converting to the browser timezone.
  return value ? value.replace("T", " ").replace(/\.\d+/, "").replace(/\+00:00|Z$/, " UTC") : "Time not retained";
}

export function DecisionTimeline({ decision, onSubmitted }: { decision: Timeline; onSubmitted?: (id: string) => void }) {
  const [cursor, setCursor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const client = useQueryClient();
  const access = useAccess();
  const stages = cursor === null ? decision.stages : decision.stages.slice(0, cursor + 1);
  const historical = cursor !== null;
  const measured = stages.some(stage => stage.stage === "measured");
  const executed = stages.some(stage => stage.stage === "executed" || stage.stage === "failed");
  const ranked = stages.some(stage => stage.stage === "ranked");
  const rec = decision.recommendation ?? decision.alternatives.find(item => item.bottleneck_id === decision.bottleneck_id);
  const canOperate = ["operator", "approver", "admin"].includes(access.role) && (import.meta.env.VITE_PUBLIC_DEPLOYMENT !== "true" || access.controlling);
  const canApprove = ["approver", "admin"].includes(access.role) && canOperate;
  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try {
      const result = await fn() as { proposal_id?: string };
      await client.invalidateQueries({ queryKey: ["analysis"] });
      if (result.proposal_id) onSubmitted?.(result.proposal_id);
    } catch (err) { setError(err instanceof Error ? err.message : "Action failed"); }
    finally { setBusy(false); }
  }
  const outcome = decision.outcome;
  const attribution = outcome?.attribution;
  const unit = attribution?.metric === "security_wait_minutes" || decision.predicted?.metric === "security_wait_minutes" ? "min" : "probability / control-rate lift";
  return <article className="card space-y-5" aria-label="Decision timeline">
    <header className="space-y-2">
      <div className="flex items-start justify-between gap-3"><h2 className="text-lg">{decision.description}</h2><span className="rounded-full bg-sky-400/10 text-sky-200 px-3 py-1 text-xs whitespace-nowrap">{historical ? "Recorded history" : decisionLabel(decision.status)}</span></div>
      <p className="text-xs text-gray-400">{decision.bottleneck?.zone ?? "Unknown target"} · {decision.bottleneck?.severity ?? "Severity not retained"} · {decision.effect_model_version}</p>
      {!decision.context_available && decision.proposal_id && <p className="text-xs text-amber-300">Original ranking context was not retained for this legacy proposal. Current evidence cannot reconstruct its original rationale.</p>}
    </header>

    <section className="rounded-xl bg-panel-active p-3 space-y-2" aria-label="Recorded decision playback">
      <div className="flex justify-between text-xs"><span className="text-gray-400">Replay recorded stages · simulation time</span>{historical && <button className="text-sky-300" onClick={() => setCursor(null)}>Return to latest</button>}</div>
      <input aria-label="Recorded stage" type="range" className="w-full accent-sky-400" min={0} max={Math.max(0, decision.stages.length - 1)} value={cursor ?? Math.max(0, decision.stages.length - 1)} disabled={!decision.stages.length} onChange={event => setCursor(Number(event.target.value))} />
      <p className="text-xs text-gray-500">Read-only history. Moving this cursor does not rewind the airport or dispatch commands.</p>
    </section>

    <ol className="space-y-0" aria-label="Decision stages">
      {stages.map((stage, index) => <li key={`${stage.stage}-${index}`} className="relative border-l border-panel-border pl-5 pb-5 last:pb-0 ml-1">
        <span className={`absolute -left-1.5 top-1 h-3 w-3 rounded-full ${["failed", "rejected"].includes(stage.stage) ? "bg-rose-400" : "bg-sky-400"}`} />
        <div className="flex flex-wrap justify-between gap-2"><h3 className="text-sm">{decisionLabel(stage.stage)}</h3><time className="font-mono text-[11px] text-gray-500">{simTimestamp(stage.at)}</time></div>
        {stage.stage === "approved" && <p className="text-xs text-gray-400 mt-1">{String(stage.details.mode ?? "Recorded")} authorization · {String(stage.details.decided_by ?? "Actor not retained")}</p>}
        {stage.stage === "dispatched" && <p className="text-xs text-gray-400 mt-1">Attempt {String(stage.details.attempt ?? "unknown")} · durably queued. Delivery and execution are separate.</p>}
        {(stage.stage === "predicted" || stage.stage === "dispatch_prediction") && <p className="text-xs text-sky-200 mt-1">{amount(typeof stage.details.delta === "number" ? stage.details.delta : typeof stage.details.probability === "number" ? stage.details.probability : undefined)} {stage.details.metric === "security_wait_minutes" ? "min wait change" : "success probability"}</p>}
        {typeof stage.details.reason === "string" && <p className="text-xs text-rose-300 mt-1">{stage.details.reason}</p>}
        {stage.details.legacy === true && <p className="text-xs text-amber-300 mt-1">Legacy timestamp; original event details not retained.</p>}
      </li>)}
      {!stages.length && <li className="text-gray-400 text-sm">No lifecycle timestamps retained.</li>}
    </ol>

    {ranked && rec && <RecommendationExplanation recommendation={rec} alternatives={decision.alternatives} />}
    {ranked && <details className="text-xs text-gray-400"><summary className="cursor-pointer text-sky-300">Financial context at proposal time</summary>
      {Object.keys(decision.financial_signals).length ? <dl className="grid sm:grid-cols-2 gap-3 mt-3">{Object.entries(decision.financial_signals).map(([name, value]) => <div key={name}><dt>{name.replace(/_/g, " ")}</dt><dd className="font-mono mt-1">{typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value ?? "Unavailable"}</dd></div>)}</dl> : <p className="mt-2">No financial signal snapshot was available. The operational ranking score is not a euro saving.</p>}
    </details>}
    {executed && <section className="text-xs text-gray-400 border-t border-panel-border pt-3">
      <h3 className="text-sm mb-1">Owner receipt</h3>
      {decision.receipt ? <p>{decision.receipt.event_type} · {decision.receipt.topic} · <span className="font-mono">{String(decision.receipt.payload.command_id)}</span></p> : <p>Receipt details were not retained. A legacy status alone does not reconstruct an owner receipt.</p>}
    </section>}
    {measured && outcome && <section className="rounded-xl bg-emerald-400/5 border border-emerald-400/20 p-4 space-y-3" aria-label="Measured outcome">
      <h3 className="text-sm">Prediction and outcome</h3>
      {outcome.measurable ? <>
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
          {[["Predicted effect", decision.predicted?.delta ?? decision.predicted?.probability], ["Observed treated change", attribution?.treated_change ?? (attribution?.treated_after != null && attribution?.treated_before != null ? attribution.treated_after - attribution.treated_before : undefined)], [attribution?.method === "pre_post" ? "Unattributed pre/post change" : "Attributed effect", attribution?.attributed_effect]].map(([name, value]) => <div key={String(name)}><dt className="text-gray-400">{String(name)}</dt><dd className="font-mono text-base mt-1">{amount(typeof value === "number" ? value : undefined)} <span className="text-xs text-gray-500">{unit}</span></dd></div>)}
        </dl>
        <p className="text-xs text-gray-400">Negative wait changes mean improvement. Attributed effects compare the treated terminal with untreated terminals.</p>
      </> : <p className="text-sm text-amber-300">Unmeasurable: {outcome.reason ?? "No outcome model or observation available."}</p>}
      <p className="text-xs text-gray-400">{attribution?.method?.replace(/_/g, " ") ?? "No attribution"} · {attribution?.control_count ?? 0} controls · {attribution?.calibration_eligible ? "Eligible for calibration" : "Excluded from calibration"}. Observational evidence; no randomized causal claim.</p>
      {attribution?.reason && <p className="text-xs text-amber-300">{attribution.reason}</p>}
    </section>}
    {!historical && decision.status === "awaiting_measurement" && <p className="text-sm text-amber-200">Owner execution is confirmed. Outcome measurement is due after 30 simulation minutes; paused simulation time does not advance the window.</p>}
    {!historical && decision.failure_reason && <p className="text-sm text-rose-300">{decision.failure_reason}</p>}
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    {!historical && <footer className="flex flex-wrap items-center gap-2">
      {!decision.proposal_id && decision.action_available && rec?.executable && <button className="btn-primary text-sm" disabled={busy || !canOperate} onClick={() => act(() => analysisApi.applyRecommendation(rec.id, true))}>Request approval</button>}
      {decision.proposal_status === "pending" && <>
        <button className="btn-primary text-sm" disabled={busy || !canApprove} onClick={() => act(() => analysisApi.approveProposal(decision.proposal_id!))}>Approve and dispatch</button>
        <button className="btn-secondary text-sm" disabled={busy || !canApprove} onClick={() => act(() => analysisApi.rejectProposal(decision.proposal_id!, "Operator rejected from decision timeline"))}>Reject</button>
      </>}
      {decision.proposal_status === "approved" && <button className="btn-primary text-sm" disabled={busy || !canApprove} onClick={() => act(() => analysisApi.approveProposal(decision.proposal_id!))}>Retry dispatch</button>}
      {(!canOperate || (decision.proposal_status === "pending" && !canApprove)) && <p className="text-xs text-gray-500">Sign in with the required operator/approver role and acquire control where enabled to act.</p>}
      <span className="text-[10px] text-gray-600 break-all">Decision {decision.id}</span>
    </footer>}
  </article>;
}
