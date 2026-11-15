import { useState } from "react";
import { Link } from "react-router-dom";
import { InjectModal } from "./InjectModal";
import { NLInjectPanel } from "./Phase5Panels";
import { SimControls } from "../../components/SimControls";

export function LabPage() {
  const [inject, setInject] = useState(false);
  if (import.meta.env.VITE_PUBLIC_DEPLOYMENT === "true") return <p className="p-6">The incident lab is unavailable in public deployments.</p>;
  return <div className="page-container space-y-6"><header><p className="section-label">Shared airport</p><h1>Incident lab</h1><p className="text-gray-400 mt-2">These actions change the shared simulation. Use isolated <Link to="/planning" className="text-accent">Experiments</Link> for comparisons that leave the airport unchanged.</p></header><section className="card space-y-4"><h2>Simulation controls</h2><SimControls /></section><section className="card space-y-3"><h2>Create an incident</h2><p className="text-gray-400">Inject a synthetic incident and follow the operational response in Incidents.</p><button className="btn-primary" onClick={() => setInject(true)}>Configure incident</button></section><details className="card"><summary>Describe an incident in natural language · changes shared airport</summary><div className="mt-4"><NLInjectPanel /></div></details><Link className="text-accent" to="/incidents">Open incident operations →</Link><InjectModal open={inject} onClose={() => setInject(false)} /></div>;
}
