import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { debugApi } from "../../hooks/useApi";
import type { Snapshot } from "./types";

export function SnapshotsPanel() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const { data: snapshotsData, isLoading } = useQuery({
    queryKey: ["snapshots"],
    queryFn: () => debugApi.listSnapshots(),
    refetchInterval: 15000,
  });

  const snapshots = (snapshotsData?.snapshots ?? []) as Snapshot[];

  const createMutation = useMutation({
    mutationFn: () => debugApi.createSnapshot(name),
    onSuccess: (data) => {
      setStatus(`Created: ${JSON.stringify(data)}`);
      setName("");
      queryClient.invalidateQueries({ queryKey: ["snapshots"] });
    },
    onError: (err) => setStatus(`Error: ${err.message}`),
  });

  const restoreMutation = useMutation({
    mutationFn: (filename: string) => debugApi.restoreSnapshot(filename),
    onSuccess: (data) => setStatus(`Restored: ${JSON.stringify(data)}`),
    onError: (err) => setStatus(`Error: ${err.message}`),
  });

  const deleteMutation = useMutation({
    mutationFn: (filename: string) => debugApi.deleteSnapshot(filename),
    onSuccess: () => {
      setStatus("Deleted");
      queryClient.invalidateQueries({ queryKey: ["snapshots"] });
    },
    onError: (err) => setStatus(`Error: ${err.message}`),
  });

  return (
    <div className="space-y-4">
      {/* Create snapshot */}
      <div className="flex gap-2">
        <input
          className="flex-1 bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
          placeholder="Snapshot name (e.g. morning-peak)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          onClick={() => createMutation.mutate()}
          disabled={!name.trim() || createMutation.isPending}
          className="px-4 py-1.5 bg-green-600 text-white rounded text-sm font-semibold
                     hover:bg-green-500 disabled:opacity-40"
        >
          {createMutation.isPending ? "Saving..." : "Save Snapshot"}
        </button>
      </div>

      {/* Snapshot list */}
      {isLoading ? (
        <p className="text-sm text-gray-400">Loading snapshots...</p>
      ) : snapshots.length === 0 ? (
        <p className="text-sm text-gray-400">No snapshots saved yet</p>
      ) : (
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {snapshots.map((snap) => (
            <div
              key={snap.snapshot_id}
              className="bg-gray-900 rounded p-3 border border-gray-800"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-white font-semibold">
                  {snap.name}
                </span>
                <span className="text-xs text-gray-400">{snap.size_kb} KB</span>
              </div>
              <div className="text-xs text-gray-400 space-y-0.5">
                <div>Sim time: {new Date(snap.sim_time).toLocaleString()}</div>
                <div>
                  Day {snap.day_number} — {snap.node_count} nodes,{" "}
                  {snap.relationship_count} rels
                </div>
                <div>Created: {new Date(snap.created_at).toLocaleString()}</div>
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => restoreMutation.mutate(snap.filename)}
                  disabled={restoreMutation.isPending}
                  className="px-3 py-1 bg-blue-600 text-white rounded text-xs
                             hover:bg-blue-500 disabled:opacity-40"
                >
                  Restore
                </button>
                <button
                  onClick={() => deleteMutation.mutate(snap.filename)}
                  disabled={deleteMutation.isPending}
                  className="px-3 py-1 bg-red-600 text-white rounded text-xs
                             hover:bg-red-500 disabled:opacity-40"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {status && (
        <pre className="bg-gray-900 text-green-400 text-xs p-3 rounded overflow-auto max-h-24 font-mono">
          {status}
        </pre>
      )}
    </div>
  );
}
