import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analysisApi, type Approval } from "../../hooks/useApi";
import { queryClient } from "../../queryClient";
import { ACTION_ICON } from "./constants";

/**
 * A9: human Approve/Reject queue for autonomous proposals.
 *
 * The autonomous engine no longer silently drops safety-guarded actions
 * (ground delay programs, passenger rebookings). It surfaces them here as
 * PENDING proposals; an operator approves (which executes the action and, when
 * it targets a concrete flight, forwards a command to `flights.commands`) or
 * rejects it.
 */
export function ApprovalQueue() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["analysis", "approvals"],
    queryFn: () => analysisApi.approvals(),
    refetchInterval: 5000,
  });

  const approvals: Approval[] = data?.approvals ?? [];

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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  if (approvals.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs text-amber-400 uppercase tracking-wide flex items-center gap-2">
        <span>⚠ Awaiting Approval</span>
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
              {ACTION_ICON[p.action_type] ?? "💡"} {p.description}
            </span>
            <span className="text-xs text-gray-400">
              {(p.confidence_score * 100).toFixed(0)}% conf.
            </span>
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {p.action_type.replace(/_/g, " ")} · proposed by {p.proposed_by}
          </div>
          <div className="flex items-center gap-2 mt-2">
            <button
              className="text-xs font-bold px-3 py-1 rounded bg-green-600 text-white hover:bg-green-500 disabled:opacity-50"
              disabled={busy === p.id}
              onClick={() => act(() => analysisApi.approveProposal(p.id), p.id)}
            >
              {busy === p.id ? "..." : "Approve"}
            </button>
            <button
              className="text-xs font-bold px-3 py-1 rounded bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
              disabled={busy === p.id}
              onClick={() =>
                act(
                  () => analysisApi.rejectProposal(p.id, "operator rejected"),
                  p.id,
                )
              }
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
