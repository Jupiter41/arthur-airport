import { useState, useCallback, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { debugApi } from "../../hooks/useApi";
import type { CypherResult } from "./types";

export function CypherConsole() {
  const [query, setQuery] = useState(
    "MATCH (f:Flight) RETURN f.flight_number, f.status LIMIT 10",
  );
  const [result, setResult] = useState<CypherResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const mutation = useMutation({
    mutationFn: () => debugApi.cypher(query),
    onSuccess: (data) => {
      setResult(data);
      setError(null);
    },
    onError: (err) => {
      setError(err.message);
      setResult(null);
    },
  });

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        mutation.mutate();
      }
    },
    [mutation],
  );

  return (
    <div className="space-y-3">
      <textarea
        ref={textareaRef}
        className="w-full h-32 bg-gray-900 text-green-400 text-sm font-mono rounded p-3
                   border border-gray-600 focus:border-blue-400 focus:outline-none resize-y"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="MATCH (n) RETURN n LIMIT 10"
        spellCheck={false}
      />
      <div className="flex items-center gap-2">
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !query.trim()}
          className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-semibold
                     hover:bg-blue-500 disabled:opacity-40"
        >
          {mutation.isPending ? "Running..." : "Execute (Ctrl+Enter)"}
        </button>
        <span className="text-xs text-gray-400">Read-only queries only</span>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {result && (
        <div className="overflow-auto max-h-80">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-gray-700">
                {result.columns.map((col) => (
                  <th
                    key={col}
                    className="text-left p-2 text-gray-400 font-semibold"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-gray-800 hover:bg-gray-800/50"
                >
                  {result.columns.map((col) => (
                    <td
                      key={col}
                      className="p-2 text-gray-300 max-w-xs truncate"
                    >
                      {JSON.stringify(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-gray-400 mt-2">
            {result.row_count} rows returned
          </p>
        </div>
      )}
    </div>
  );
}
