import { useMemo } from "react";
import { useConnectionStore } from "../stores/connectionStore";

function Dot({ online }: { online: boolean | null }) {
  if (online === null) {
    return <span className="inline-block h-2 w-2 rounded-full bg-gray-500" />;
  }
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${online ? "bg-emerald-400" : "bg-red-400"}`}
    />
  );
}

function formatLastSeen(iso: string | null): string {
  if (!iso) {
    return "no events yet";
  }
  const deltaMs = Date.now() - new Date(iso).getTime();
  const sec = Math.max(0, Math.floor(deltaMs / 1000));
  if (sec < 60) {
    return `${sec}s ago`;
  }
  return `${Math.floor(sec / 60)}m ago`;
}

export function ConnectionStatus() {
  const {
    apiConnected,
    wsConnected,
    wsLastMessageAt,
    lastApiError,
    lastWsError,
  } = useConnectionStore();

  const title = useMemo(() => {
    const lines = [
      `API: ${apiConnected === null ? "unknown" : apiConnected ? "online" : "offline"}`,
      `WS: ${wsConnected ? "connected" : "disconnected"}`,
      `Last WS event: ${formatLastSeen(wsLastMessageAt)}`,
    ];
    if (lastApiError) {
      lines.push(`API error: ${lastApiError}`);
    }
    if (lastWsError) {
      lines.push(`WS error: ${lastWsError}`);
    }
    return lines.join("\n");
  }, [apiConnected, wsConnected, wsLastMessageAt, lastApiError, lastWsError]);

  return (
    <div
      className="flex items-center gap-3 rounded border border-gray-600 bg-gray-700/50 px-2 py-1"
      title={title}
    >
      <div className="flex items-center gap-1 text-[10px] text-gray-300 uppercase tracking-wide">
        <Dot online={apiConnected} />
        <span>API</span>
      </div>
      <div className="flex items-center gap-1 text-[10px] text-gray-300 uppercase tracking-wide">
        <Dot online={wsConnected} />
        <span>WS</span>
      </div>
    </div>
  );
}
