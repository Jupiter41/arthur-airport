import { useState, useEffect, useCallback } from "react";
import { analysisApi } from "../../hooks/useApi";

/* ── Natural Language Query Panel (P5-2-1) ── */

export function NLQueryPanel() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [source, setSource] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await analysisApi.query(question);
      setAnswer(result.answer);
      setSource(result.source);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed");
    } finally {
      setLoading(false);
    }
  }, [question]);

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
        <span>💬</span> Ask about Operations
        <span className="text-[10px] text-gray-500 font-normal">P5-2-1</span>
      </h3>
      <div className="flex gap-2 mb-3">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="How many flights are delayed?"
          className="flex-1 bg-gray-700 text-white text-sm rounded px-3 py-2
            placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <button
          onClick={handleSubmit}
          disabled={loading || !question.trim()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600
            text-white text-sm rounded transition-colors"
        >
          {loading ? "..." : "Ask"}
        </button>
      </div>
      {error && <div className="text-xs text-red-400 mb-2">{error}</div>}
      {answer && (
        <div className="bg-gray-700/50 rounded p-3">
          <pre className="text-sm text-gray-200 whitespace-pre-wrap font-sans">
            {answer}
          </pre>
          <div className="text-[10px] text-gray-500 mt-2">Source: {source}</div>
        </div>
      )}
      <div className="flex gap-2 mt-2 flex-wrap">
        {[
          "How many flights are delayed?",
          "What's the security queue status?",
          "Any active incidents?",
          "What's the weather like?",
        ].map((q) => (
          <button
            key={q}
            onClick={() => {
              setQuestion(q);
            }}
            className="text-[10px] text-gray-400 bg-gray-700 hover:bg-gray-600
              px-2 py-1 rounded transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Natural Language Incident Injection (P5-2-2) ── */

export function NLInjectPanel() {
  const [command, setCommand] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (!command.trim()) return;
    setLoading(true);
    try {
      const res = (await analysisApi.nlInject(command)) as Record<
        string,
        unknown
      >;
      setResult(res);
    } catch {
      setResult({ error: "Injection failed" });
    } finally {
      setLoading(false);
    }
  }, [command]);

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
        <span>🎯</span> Natural Language Injection
        <span className="text-[10px] text-gray-500 font-normal">P5-2-2</span>
      </h3>
      <div className="flex gap-2 mb-3">
        <input
          type="text"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="Inject a severe security breach in Terminal B"
          className="flex-1 bg-gray-700 text-white text-sm rounded px-3 py-2
            placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <button
          onClick={handleSubmit}
          disabled={loading || !command.trim()}
          className="px-4 py-2 bg-orange-600 hover:bg-orange-500 disabled:bg-gray-600
            text-white text-sm rounded transition-colors"
        >
          {loading ? "..." : "Parse"}
        </button>
      </div>
      {result && (
        <pre className="text-xs text-gray-300 bg-gray-700/50 rounded p-2 overflow-auto max-h-40">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}

/* ── Anomaly Detection Panel (P5-3-1) ── */

interface AnomalyData {
  trained: boolean;
  buffer_size: number;
  min_samples: number;
  anomalies: {
    score: number;
    normalized_score: number;
    status: string;
    z_scores: Record<string, number>;
    root_cause: string | null;
    root_cause_feature: string | null;
    detected_at: string | null;
  } | null;
}

const STATUS_COLORS: Record<string, string> = {
  normal: "text-green-400",
  amber: "text-amber-400",
  red: "text-red-400",
};

const STATUS_BG: Record<string, string> = {
  normal: "bg-green-900/30",
  amber: "bg-amber-900/30",
  red: "bg-red-900/30",
};

export function AnomalyPanel() {
  const [data, setData] = useState<AnomalyData | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = (await analysisApi.anomalies()) as AnomalyData;
      setData(result);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30000); // refresh every 30s
    return () => clearInterval(interval);
  }, [refresh]);

  if (!data) {
    return (
      <div className="bg-gray-800 rounded p-4 text-gray-400 text-sm">
        Loading anomaly detection...
      </div>
    );
  }

  const anomaly = data.anomalies;
  const status = anomaly?.status ?? "normal";

  return (
    <div className={`${STATUS_BG[status]} rounded p-4`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <span>🔍</span> Anomaly Detection
          <span className="text-[10px] text-gray-500 font-normal">P5-3-1</span>
        </h3>
        <div className="flex items-center gap-2">
          <span
            className={`text-xs font-bold uppercase ${STATUS_COLORS[status]}`}
          >
            {status}
          </span>
          <button
            onClick={refresh}
            disabled={loading}
            className="text-[10px] text-gray-400 hover:text-white"
          >
            ↻
          </button>
        </div>
      </div>

      {!data.trained ? (
        <div className="text-xs text-gray-400">
          Collecting baseline data... ({data.buffer_size}/{data.min_samples}{" "}
          samples)
          <div className="w-full bg-gray-700 rounded-full h-1 mt-1">
            <div
              className="bg-blue-500 rounded-full h-1 transition-all"
              style={{
                width: `${Math.min(100, (data.buffer_size / data.min_samples) * 100)}%`,
              }}
            />
          </div>
        </div>
      ) : anomaly ? (
        <div className="space-y-2">
          <div className="flex gap-4 text-xs">
            <span className="text-gray-400">
              Score: <span className="text-white">{anomaly.score}</span>
            </span>
            <span className="text-gray-400">
              Normalized:{" "}
              <span className="text-white">
                {(anomaly.normalized_score * 100).toFixed(0)}%
              </span>
            </span>
          </div>

          {anomaly.root_cause && (
            <div className="text-xs bg-gray-800/50 rounded p-2">
              <span className="text-gray-400">Root cause: </span>
              <span className="text-white">{anomaly.root_cause}</span>
            </div>
          )}

          {/* Top z-scores */}
          {anomaly.z_scores && Object.keys(anomaly.z_scores).length > 0 && (
            <div className="text-xs">
              <span className="text-gray-400">Top deviations:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {Object.entries(anomaly.z_scores)
                  .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                  .slice(0, 5)
                  .map(([feat, z]) => (
                    <span
                      key={feat}
                      className={`px-1.5 py-0.5 rounded ${Math.abs(z) > 2 ? "bg-red-900/50 text-red-300" : Math.abs(z) > 1 ? "bg-amber-900/50 text-amber-300" : "bg-gray-700 text-gray-300"}`}
                    >
                      {feat}: {z > 0 ? "+" : ""}
                      {z.toFixed(1)}σ
                    </span>
                  ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="text-xs text-gray-400">
          Model trained, awaiting data
        </div>
      )}
    </div>
  );
}

/* ── Narration Feed (P5-2-3) ── */

interface NarrationEntry {
  text: string;
  sim_time: string | null;
  event_count: number;
  source: string;
}

export function NarrationFeed() {
  const [entries, setEntries] = useState<NarrationEntry[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const result = (await analysisApi.narration(20)) as {
        settings: { enabled: boolean };
        history: NarrationEntry[];
      };
      setEntries(result.history);
      setEnabled(result.settings.enabled);
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = useCallback(async () => {
    setLoading(true);
    try {
      await analysisApi.updateNarration({ enabled: !enabled });
      setEnabled(!enabled);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, [refresh]);

  return (
    <div className="bg-gray-800 rounded p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <span>📢</span> Live Narration
          <span className="text-[10px] text-gray-500 font-normal">P5-2-3</span>
        </h3>
        <button
          onClick={toggle}
          disabled={loading}
          className={`text-xs px-2 py-1 rounded transition-colors ${
            enabled
              ? "bg-green-700 text-green-200 hover:bg-green-600"
              : "bg-gray-700 text-gray-400 hover:bg-gray-600"
          }`}
        >
          {enabled ? "ON" : "OFF"}
        </button>
      </div>

      {!enabled ? (
        <div className="text-xs text-gray-400">
          Narration is disabled. Toggle ON to receive live commentary.
        </div>
      ) : entries.length === 0 ? (
        <div className="text-xs text-gray-400">
          Waiting for significant events...
        </div>
      ) : (
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {entries.map((entry, i) => (
            <div key={i} className="text-xs border-l-2 border-blue-500 pl-2">
              <div className="text-gray-200">{entry.text}</div>
              <div className="text-[10px] text-gray-500 mt-0.5">
                {entry.sim_time
                  ? new Date(entry.sim_time).toLocaleTimeString()
                  : "--"}{" "}
                · {entry.event_count} events · {entry.source}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── After-Action Report (P5-2-4) ── */

export function ReportGenerator() {
  const [report, setReport] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const generate = useCallback(async () => {
    setLoading(true);
    try {
      const result = await analysisApi.generateReport();
      setReport(result.report);
    } catch {
      setReport("Failed to generate report.");
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="bg-gray-800 rounded p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <span>📄</span> After-Action Report
          <span className="text-[10px] text-gray-500 font-normal">P5-2-4</span>
        </h3>
        <button
          onClick={generate}
          disabled={loading}
          className="px-3 py-1 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600
            text-white text-xs rounded transition-colors"
        >
          {loading ? "Generating..." : "Generate Report"}
        </button>
      </div>
      {report && (
        <div className="bg-gray-700/50 rounded p-3 max-h-64 overflow-y-auto">
          <pre className="text-xs text-gray-200 whitespace-pre-wrap font-sans">
            {report}
          </pre>
        </div>
      )}
    </div>
  );
}
