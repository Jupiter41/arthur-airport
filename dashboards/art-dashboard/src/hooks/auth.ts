import { useSyncExternalStore } from "react";

const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim().replace(/\/+$/, "") ?? "";
let token: string | null = null;
let tokenExpires = 0;
let role = "viewer";
let lease: string | null = null;
let tokenPromise: Promise<string> | null = null;
let snapshot = { role, controlling: false };
const listeners = new Set<() => void>();
function notifyAccess() {
  if (snapshot.role === role && snapshot.controlling === (lease !== null)) return;
  snapshot = { role, controlling: lease !== null };
  listeners.forEach(fn => fn());
}
export function useAccess() {
  return useSyncExternalStore(fn => { listeners.add(fn); return () => listeners.delete(fn); }, () => snapshot);
}

// Credentials and operator tokens live only in this page's memory. Each tab
// gets a separate session and must explicitly acquire control.
async function issue(path: string, body: unknown): Promise<string> {
  const res = await fetch(`${API_ORIGIN}/auth/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Sign-in failed (${res.status})`);
  const data = await res.json() as { token: string; expires_in: number; role: string };
  token = data.token; role = data.role; lease = null;
  tokenExpires = Date.now() + data.expires_in * 1000 - 10_000;
  notifyAccess();
  return token;
}
export async function getAuthToken(forceRefresh = false): Promise<string> {
  if (!forceRefresh && token && Date.now() < tokenExpires) return token;
  if (!tokenPromise) {
    tokenPromise = issue("viewer", {}).finally(() => { tokenPromise = null; });
  }
  return tokenPromise;
}
export async function operatorLogin(client_id: string, secret: string): Promise<void> {
  if (tokenPromise) await tokenPromise.catch(() => undefined);
  await issue("token", { client_id, secret });
}
export function accessState() { return { role, controlling: lease !== null }; }
export function controlHeaders(): Record<string, string> { return lease ? { "X-Control-Lease": lease } : {}; }
export async function controlRequest(action: "status" | "acquire" | "release") {
  const bearer = await getAuthToken();
  const res = await fetch(`${API_ORIGIN}/api/v1/control`, {
    method: action === "status" ? "GET" : action === "release" ? "DELETE" : "POST",
    headers: { Authorization: `Bearer ${bearer}`, ...controlHeaders() },
  });
  const data = await res.json() as { lease?: string; owner?: string; controlling?: boolean; expires_at?: number; enabled?: boolean; error?: string };
  if (!res.ok) {
    if (action !== "status") lease = null;
    notifyAccess();
    throw new Error(data.error ?? "Could not acquire control");
  }
  if (action === "acquire") lease = data.lease ?? null;
  if (action === "release" || !data.owner) lease = null;
  if (action === "status" && !data.controlling) lease = null;
  notifyAccess();
  return data;
}
export function logout() { token = null; tokenExpires = 0; role = "viewer"; lease = null; notifyAccess(); }
