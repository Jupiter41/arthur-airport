import { useState } from "react";
import type { Tab } from "./types";
import { TABS } from "./types";
import ScenarioBuilder from "./components/ScenarioBuilder";
import ResultsTab from "./components/ResultsTab";
import InvestmentTab from "./components/InvestmentTab";
import AuditTab from "./components/AuditTab";

export default function PlanningPage() {
  const [activeTab, setActiveTab] = useState<Tab>("builder");

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">
          Capacity Planning & Investment Analysis
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          What-if scenarios for KART infrastructure — Monte Carlo simulation ×
          Discounted Cash Flow analysis
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-slate-800/50 rounded-xl p-1 border border-slate-700">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`flex-1 py-2.5 px-4 rounded-lg text-sm font-medium transition-all ${
              activeTab === t.key
                ? "bg-slate-700 text-white shadow-lg"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
            }`}
          >
            <span className="mr-1.5">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* Active tab content */}
      {activeTab === "builder" && <ScenarioBuilder />}
      {activeTab === "results" && <ResultsTab />}
      {activeTab === "investment" && <InvestmentTab />}
      {activeTab === "audit" && <AuditTab />}
    </div>
  );
}
