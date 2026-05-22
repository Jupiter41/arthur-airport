import { useState } from "react";
import { TABS, type TabId } from "./types";
import { InjectionPanel } from "./InjectionPanel";
import { EntityInspector } from "./EntityInspector";
import { CypherConsole } from "./CypherConsole";
import { KafkaInspector } from "./KafkaInspector";
import { WeatherSourcePanel } from "./WeatherSourcePanel";
import { SnapshotsPanel } from "./SnapshotsPanel";
import { WeatherHistoryChart } from "./WeatherHistoryChart";

export default function DebugPage() {
  const [activeTab, setActiveTab] = useState<TabId>("inject");

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          🛠️ Debug Panel
        </h1>
        <span className="text-xs text-gray-400 bg-gray-800 px-2 py-1 rounded font-mono">
          Ctrl+D to toggle
        </span>
      </div>

      {/* Weather history sparkline at top */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-3">
        <WeatherHistoryChart />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-800 p-1 rounded-lg">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 text-sm rounded transition-colors ${
              activeTab === tab.id
                ? "bg-gray-700 text-white font-semibold"
                : "text-gray-400 hover:text-gray-300 hover:bg-gray-700/50"
            }`}
          >
            <span>{tab.icon}</span>
            <span className="hidden lg:inline">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        {activeTab === "inject" && <InjectionPanel />}
        {activeTab === "inspector" && <EntityInspector />}
        {activeTab === "cypher" && <CypherConsole />}
        {activeTab === "kafka" && <KafkaInspector />}
        {activeTab === "weather" && <WeatherSourcePanel />}
        {activeTab === "snapshots" && <SnapshotsPanel />}
      </div>
    </div>
  );
}

export { WeatherHistoryChart };
