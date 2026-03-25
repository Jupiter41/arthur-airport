import { Request, Response } from "express";
import { UPSTREAM } from "./proxy";
import { isKafkaConnected, isKafkaFresh, getLastMessageAt } from "./kafka";

const SERVICE_KEYS: Record<string, string> = {
  flight_service: "flights",
  passenger_service: "passengers",
  baggage_service: "baggage",
  weather_service: "weather",
  incident_service: "incidents",
  sim_orchestrator: "sim",
};

async function checkService(baseUrl: string): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3_000);
    const resp = await fetch(`${baseUrl}/health`, {
      signal: controller.signal,
    });
    clearTimeout(timer);
    return resp.ok;
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

  // Check at least one upstream is reachable
  let anyUpstreamOk = false;
  for (const key of Object.values(SERVICE_KEYS)) {
    const ok = await checkService(UPSTREAM[key]);
    if (ok) {
      anyUpstreamOk = true;
      break;
    }
  }

  if (!kafkaOk || !kafkaFresh || !anyUpstreamOk) {
    res.status(503).json({
      status: "not ready",
      kafka: kafkaOk,
      kafka_fresh: kafkaFresh,
      upstream: anyUpstreamOk,
    });
    return;
  }

  res.json({
    status: "ready",
    kafka: kafkaOk,
    kafka_fresh: kafkaFresh,
    upstream: anyUpstreamOk,
  });
}
