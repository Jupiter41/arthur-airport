import { Request, Response } from "express";
import { UPSTREAM } from "./proxy";

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

async function read(url: string): Promise<Record<string, unknown> | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(url, { signal: controller.signal, redirect: "error" });
    if (!response.ok || !response.body) return null;
    const chunks: Uint8Array[] = [];
    let size = 0;
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > 512 * 1024) { controller.abort(); return null; }
      chunks.push(chunk);
    }
    const body: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    return object(body) ? body : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

function observation(body: Record<string, unknown> | null, keys: string[]) {
  const values = body?.values;
  if (!object(values) || !keys.every(key => typeof values[key] === "number" && Number.isFinite(values[key])) ||
      !(body?.sim_time === null || (typeof body?.sim_time === "string" && Number.isFinite(Date.parse(body.sim_time))))) {
    return { status: "unavailable", sim_time: null, values: null };
  }
  return { status: "available", sim_time: body.sim_time, values: Object.fromEntries(keys.map(key => [key, values[key]])) };
}

/** Aggregate owner observations only; no cross-domain setting execution. */
export async function handleSettings(_req: Request, res: Response): Promise<void> {
  const [requested, passenger, baggage] = await Promise.all([
    read(`${UPSTREAM.sim}/api/v1/sim/settings`),
    read(`${UPSTREAM.passengers}/api/v1/flow/configuration`),
    read(`${UPSTREAM.baggage}/api/v1/baggage/configuration`),
  ]);
  if (!requested || !object(requested.requested) || !object(requested.application)) {
    res.status(502).json({ error: "Settings contract unavailable from orchestrator" });
    return;
  }
  res.json({ ...requested, effective: {
    passenger: observation(passenger, ["lanes_a", "lanes_b", "lanes_c", "mct_minutes"]),
    baggage: observation(baggage, ["screening_units", "sorting_capacity", "dg_false_positive_rate"]),
  } });
}
