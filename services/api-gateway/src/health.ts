import { Request, Response } from "express";
import { buildRequired, getBuildIdentity, matchesBuild, BuildIdentity } from "./buildIdentity";
import { UPSTREAM } from "./proxy";
import { isKafkaConnected, isKafkaFresh, getLastMessageAt } from "./kafka";

const SERVICE_KEYS: Record<string, string> = {
  flight_service: "flights",
  passenger_service: "passengers",
  baggage_service: "baggage",
  weather_service: "weather",
  incident_service: "incidents",
  sim_orchestrator: "sim",
  analysis_service: "analysis",
  cost_service: "costs",
  planning_service: "planning",
};

async function checkService(baseUrl: string): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3_000);
    try {
      const resp = await fetch(`${baseUrl}/ready`, {
        signal: controller.signal,
      });
      await resp.body?.cancel();
      return resp.ok;
    } finally {
      clearTimeout(timer);
    }
  } catch {
    return false;
  }
}

export async function handleServicesHealth(
  _req: Request,
  res: Response,
): Promise<void> {
  const checks = await Promise.allSettled(
    Object.entries(SERVICE_KEYS).map(async ([name, key]) => {
      const ok = await checkService(UPSTREAM[key]);
      return { name, ok };
    }),
  );

  const result: Record<string, string> = {
    gateway: "ok",
  };

  for (const check of checks) {
    if (check.status === "fulfilled") {
      result[check.value.name] = check.value.ok ? "ok" : "unavailable";
    } else {
      result["unknown"] = "error";
    }
  }

  result.kafka = isKafkaConnected() ? "ok" : "unavailable";
  const lma = getLastMessageAt();
  result.kafka_fresh = isKafkaFresh() ? "ok" : "stale";
  if (lma !== null) {
    result.kafka_last_message_age_ms = String(Date.now() - lma);
  }

  res.json(result);
}

export async function handleReady(_req: Request, res: Response): Promise<void> {
  const kafkaOk = isKafkaConnected();
  const kafkaFresh = isKafkaFresh();

  const checks = await Promise.all(
    Object.entries(SERVICE_KEYS).map(async ([name, key]) =>
      [name, await checkService(UPSTREAM[key])] as const,
    ),
  );
  const services = Object.fromEntries(checks);
  const allUpstreamsOk = checks.every(([, ok]) => ok);
  const localBuild = getBuildIdentity();
  const identity = buildRequired() ? await Promise.all(Object.entries(SERVICE_KEYS).map(async ([name, key]) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    try {
      const response = await fetch(`${UPSTREAM[key]}/build`, {signal:controller.signal, redirect:"error"});
      if (!response.ok) { await response.body?.cancel(); return [name, false] as const; }
      const owner = await response.json() as BuildIdentity;
      return [name, matchesBuild(owner,localBuild,name.replaceAll("_", "-"))] as const;
    } catch { return [name,false] as const; }
    finally { clearTimeout(timer); }
  })) : [];
  const buildOk = !buildRequired() || (localBuild.integrity && identity.every(([,ok]) => ok));

  if (!kafkaOk || !kafkaFresh || !allUpstreamsOk || !buildOk) {
    res.status(503).json({
      status: "not ready",
      kafka: kafkaOk,
      kafka_fresh: kafkaFresh,
      upstream: allUpstreamsOk,
      services,
      build_identity: buildOk,
      identity: Object.fromEntries(identity),
    });
    return;
  }

  res.json({
    status: "ready",
    kafka: kafkaOk,
    kafka_fresh: kafkaFresh,
    upstream: allUpstreamsOk,
    services,
    build_identity: buildOk,
    identity: Object.fromEntries(identity),
  });
}
