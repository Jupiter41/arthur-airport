import { useAccess } from "../../hooks/auth";
import { Link } from "react-router-dom";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analysisApi, type Approval } from "../../hooks/useApi";
import { queryClient } from "../../queryClient";

/**
 * A9: human Approve/Reject queue for autonomous proposals.
 *
 * The autonomous engine no longer silently drops safety-guarded actions
 * (ground delay programs, passenger rebookings). It surfaces them here as
 * PENDING proposals; an operator approves (which executes the action and, when
 * it targets a concrete flight, forwards a command to `flights.commands`) or
 * rejects it.
 */
export function ApprovalQueue({ pendingOnly = false }: { pendingOnly?: boolean }) {
  const access=useAccess();
  const canApprove=["approver","admin"].includes(access.role)&&(import.meta.env.VITE_PUBLIC_DEPLOYMENT!=="true"||access.controlling);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data, isError, isLoading } = useQuery({
    queryKey: ["analysis", "approvals"],
    queryFn: () => analysisApi.approvals(true),
    refetchInterval: 5000,
  });

  const approvals: Approval[] = (data?.approvals ?? []).filter(
    p => pendingOnly ? ["pending", "approved", "dispatched"].includes(p.status) : p.status !== "rejected",
  ).slice(-20).reverse();

  async function act(fn: () => Promise<unknown>, id: string) {
    setBusy(id);
    setError(null);
    try {
      await fn();
      await queryClient.invalidateQueries({
        queryKey: ["analysis", "approvals"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["analysis", "autonomous", "log"],
      });
      await queryClient.invalidateQueries({ queryKey: ["analysis", "decisions"] });
      await queryClient.invalidateQueries({ queryKey: ["analysis", "decision"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  if (approvals.length === 0) {
    if (pendingOnly) return <div><h2 className="text-sm mb-2">Pending approvals &amp; commands</h2><p className={isError ? "text-amber-300 text-xs" : "text-gray-500 text-xs"}>{isError ? "Approval queue unavailable." : isLoading ? "Loading approvals…" : "No pending approvals or commands."}</p></div>;
    return null;
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs text-amber-400 uppercase tracking-wide flex items-center gap-2">
        <span>Action proposals</span>
        <span className="text-gray-500">({approvals.length})</span>
      </h3>

      {error && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded px-2 py-1">
          {error}
        </div>
      )}

      {approvals.map((p) => (
        <div
          key={p.id}
          className="ring-1 ring-amber-500/60 bg-gray-800 rounded p-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm text-white font-medium">
              {p.description}
            </span>
            <span className="text-xs text-gray-400">
              {(p.confidence_score * 100).toFixed(0)}% conf.
            </span>
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {p.action_type.replace(/_/g, " ")} · proposed by {p.proposed_by}
          </div>
          <div className="text-xs text-gray-300 mt-1">
            {p.status === "dispatched" ? "Awaiting execution" : p.status}
            {p.failure_reason ? `: ${p.failure_reason}` : ""}
          </div>
          <Link className="text-accent text-xs block mt-2" to={`/decisions?decision=${encodeURIComponent(p.id)}`}>Review evidence & outcome →</Link>
          {!canApprove && p.status === "pending" && <p className="text-xs text-gray-400 mt-2">Approval requires an approver account and control where enabled.</p>}
          {["pending", "approved"].includes(p.status) && <div className="flex items-center gap-2 mt-2">
            <button
              className="text-xs font-bold px-3 py-1 rounded bg-green-600 text-white hover:bg-green-500 disabled:opacity-50"
              disabled={busy === p.id || !canApprove}
              onClick={() => act(() => analysisApi.approveProposal(p.id), p.id)}
            >
              {busy === p.id ? "..." : p.status === "approved" ? "Retry dispatch" : "Approve"}
            </button>
            {p.status === "pending" && <button
              className="text-xs font-bold px-3 py-1 rounded bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
              disabled={busy === p.id || !canApprove}
              onClick={() =>
                act(
                  () => analysisApi.rejectProposal(p.id, "operator rejected"),
                  p.id,
                )
              }
            >
              Reject
            </button>}
          </div>}
        </div>
      ))}
    </div>
  );
}
