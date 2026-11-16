import { Link, useSearchParams } from "react-router-dom";
import type { Tab } from "./types";
import { TABS } from "./types";
import ScenarioBuilder from "./components/ScenarioBuilder";
import ResultsTab from "./components/ResultsTab";
import InvestmentTab from "./components/InvestmentTab";
import AuditTab from "./components/AuditTab";

export default function PlanningPage() {
  const [params, setParams] = useSearchParams();
  const activeTab = (params.get("tab") ?? "builder") as Tab;
  const setActiveTab = (tab: Tab) => {
    const next = new URLSearchParams(params);
    next.set("tab", tab);
    setParams(next);
  };

  return (
    <div className="page-container space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Experiments</h1>
        <p className="text-sm text-slate-400 mt-1">
          Choose a baseline, change capacity, run an isolated experiment and
          compare its results.
        </p>
      </div>

      <p className="card text-sm text-gray-300">
        Isolated experiment · changes do not affect the shared airport.{" "}
        <Link className="text-accent" to="/scenarios">
          Shared-airport scenarios are in System.
        </Link>
      </p>
      <ol
        aria-label="Experiment workflow"
        className="flex flex-wrap gap-3 text-sm text-gray-400"
      >
        {[
          "1. Baseline",
          "2. Changes",
          "3. Run",
          "4. Compare",
          "5. Save & review",
        ].map((label) => (
          <li key={label}>{label}</li>
        ))}
      </ol>
      <Link className="text-accent text-sm" to="/whatif">
        Replay a completed experiment with interventions →
      </Link>
      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 bg-slate-800/50 rounded-xl p-1 border border-slate-700">
        {TABS.map((t) => (
          <button
            key={t.key}
            aria-pressed={activeTab === t.key}
            onClick={() => setActiveTab(t.key)}
            className={`flex-1 min-w-[120px] py-2.5 px-4 rounded-lg text-sm font-medium transition-all ${
              activeTab === t.key
                ? "bg-slate-700 text-white shadow-lg"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Active tab content */}
      <div hidden={activeTab !== "builder"}>
        <ScenarioBuilder />
      </div>
      {activeTab === "results" && <ResultsTab />}
      {activeTab === "investment" && <InvestmentTab />}
      {activeTab === "audit" && <AuditTab />}
    </div>
  );
}
