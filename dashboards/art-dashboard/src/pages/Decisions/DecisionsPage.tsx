import { DecisionWorkspace } from "./DecisionWorkspace";
import { TeachingRunbook } from "./TeachingRunbook";

export default function DecisionsPage() {
  return <div className="h-full overflow-y-auto p-4 md:p-6 space-y-6 max-w-[1600px] mx-auto">
    <header><p className="text-xs tracking-[0.2em] uppercase text-sky-300">Living digital twin</p><h1 className="text-2xl mt-2">Decision history</h1><p className="text-sm text-gray-400 mt-2">Follow what the airport observed, what it recommended, what was executed, and what changed.</p></header>
    <DecisionWorkspace />
    <TeachingRunbook />
  </div>;
}
