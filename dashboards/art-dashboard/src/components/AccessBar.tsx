import { useEffect, useState } from "react";
import { Dialog } from "./Dialog";
import { accessState, controlRequest, operatorLogin, logout } from "../hooks/auth";

export function AccessBar() {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState(accessState);
  const [owner, setOwner] = useState<string | null>(null);
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const poll = async () => {
      try {
        const result = await controlRequest("status");
        setOwner(result.owner ?? null); setState(accessState());
      } catch { /* ConnectionStatus handles unavailable gateway. */ }
    };
    void poll();
    const timer = setInterval(poll, 15_000);
    const renewal = setInterval(() => {
      if (accessState().controlling) void controlRequest("acquire")
        .then(() => setState(accessState()))
        .catch((err: Error) => { setError(err.message); setState(accessState()); });
    }, 45_000);
    return () => { clearInterval(timer); clearInterval(renewal); };
  }, []);
  async function perform(fn: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await fn(); const s = await controlRequest("status"); setOwner(s.owner ?? null); }
    catch (err) { setError(err instanceof Error ? err.message : "Access request failed"); }
    finally { setState(accessState()); setBusy(false); }
  }
  return <><button className="btn-secondary text-sm" onClick={() => setOpen(true)}>{state.controlling ? "Controlling" : state.role === "viewer" ? "Viewer / sign in" : state.role}</button>{open && <Dialog title="Account & airport control" onClose={() => { setOpen(false); setSecret(""); }}><div className="space-y-4 text-sm">
    <span>{state.controlling ? "You control the shared airport" : owner ? `Controlled by ${owner}` : "Shared airport · viewing"}</span>
    {state.role === "viewer" ? <form className="grid gap-3" onSubmit={e => {
      e.preventDefault(); const password = secret; setSecret("");
      void perform(() => operatorLogin(clientId, password));
    }}>
      <input aria-label="Operator ID" placeholder="Operator ID" autoComplete="username" value={clientId} onChange={e => setClientId(e.target.value)} className="bg-panel border border-panel-border rounded px-2 py-1" required />
      <input aria-label="Operator password" placeholder="Password" type="password" autoComplete="current-password" value={secret} onChange={e => setSecret(e.target.value)} className="bg-panel border border-panel-border rounded px-2 py-1" required />
      <button className="btn-secondary" disabled={busy} type="submit">Operator sign in</button>
    </form> : <>
      <button className="btn-secondary" disabled={busy} onClick={() => void perform(() => controlRequest(state.controlling ? "release" : "acquire"))}>
        {state.controlling ? "Release control" : "Acquire control"}
      </button>
      <button className="btn-secondary" disabled={busy} onClick={() => void perform(async () => {
        if (accessState().controlling) await controlRequest("release"); logout();
      })}>Sign out</button>
    </>}
    {!state.controlling && <span className="text-gray-400">Parameter changes require operator control.</span>}
    {error && <span role="alert" className="text-amber-400">{error}</span>}
  </div></Dialog>}</>;
}
