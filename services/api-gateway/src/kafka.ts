import { Kafka, Consumer, EachMessagePayload } from "kafkajs";
import {
  fanOut,
  setCurrentSimTime,
  cacheLatestEvent,
  setSimMode,
} from "./websocket";

const TOPIC_KEY_MAP: Record<string, string> = {
  "sim.clock": "sim",
  "flights.events": "flights",
  "passengers.events": "passengers",
  "baggage.events": "baggage",
  "weather.events": "weather",
  "incidents.events": "incidents",
  "incidents.alerts": "alerts",
  "ground.events": "flights",
  "analysis.events": "analysis",
  "cost.events": "costs",
};

const ALL_TOPICS = Object.keys(TOPIC_KEY_MAP);

let consumer: Consumer | null = null;
let connected = false;
let lastMessageAt: number | null = null;
let lastHeartbeatAt: number | null = null;
let stopping = false;
let starting: Promise<void> | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

const FRESHNESS_THRESHOLD_MS = Math.max(30_000,
  Number(process.env.KAFKA_FRESHNESS_THRESHOLD_MS) || 30_000);

export function isKafkaConnected(): boolean {
  return connected;
}

export function isKafkaFresh(): boolean {
  if (!connected) return false;
  const activity = Math.max(lastMessageAt ?? 0, lastHeartbeatAt ?? 0);
  return activity > 0 && Date.now() - activity < FRESHNESS_THRESHOLD_MS;
}

export function getLastMessageAt(): number | null {
  return lastMessageAt;
}

function scheduleRetry(): void {
  if (stopping || retryTimer) return;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    if (!stopping) void setupKafka();
  }, 1000);
  retryTimer.unref();
}

export function setupKafka(): Promise<void> {
  if (starting) return starting;
  if (connected) return Promise.resolve();
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  stopping = false;
  starting = startAttempt().finally(() => { starting = null; });
  return starting;
}

async function startAttempt(): Promise<void> {
  const brokers = (process.env.KAFKA_BROKERS ?? "kafka:9092").split(",");
  const groupId = process.env.KAFKA_GROUP_ID ?? "api-gateway";

  const kafka = new Kafka({
    clientId: "api-gateway",
    brokers,
    retry: {
      initialRetryTime: 1000,
      retries: 10,
    },
  });

  const previous = consumer;
  consumer = null;
  connected = false;
  lastHeartbeatAt = null;
  if (previous) await previous.disconnect().catch(err => console.error("[Kafka] Disconnect failed:", err));
  if (stopping) return;
  const next = kafka.consumer({ groupId });
  consumer = next;
  next.on(next.events.GROUP_JOIN, () => {
    if (consumer !== next || stopping) return;
    connected = true;
    lastHeartbeatAt = Date.now();
  });
  next.on(next.events.HEARTBEAT, () => {
    if (consumer === next && connected) lastHeartbeatAt = Date.now();
  });
  next.on(next.events.DISCONNECT, () => {
    if (consumer === next) connected = false;
  });
  next.on(next.events.CRASH, event => {
    if (consumer !== next || stopping) return;
    connected = false;
    // KafkaJS owns retriable runtime crashes; replace only when it gives up.
    if (!event.payload.restart) scheduleRetry();
  });

  try {
    await next.connect();
    if (stopping || consumer !== next) return;
    console.log("[Kafka] Consumer connected");

    await next.subscribe({ topics: ALL_TOPICS, fromBeginning: false });
    if (stopping || consumer !== next) return;

    await next.run({
      eachMessage: async ({ topic, message }: EachMessagePayload) => {
        lastMessageAt = Date.now();
        try {
          const value = message.value?.toString();
          if (!value) return;

          const event = JSON.parse(value);
          const topicKey = TOPIC_KEY_MAP[topic] ?? topic;

          // Cache sim_time from clock ticks
          if (event.event_type === "SimClockTick") {
            const tickSimTime = event.sim_time ?? event.payload?.sim_time;
            if (typeof tickSimTime === "string") {
              setCurrentSimTime(tickSimTime);
            }
            // Track simulation mode for WebSocket throttling
            const mode = event.payload?.mode;
            if (typeof mode === "string") {
              setSimMode(mode);
            }
          }

          // Cache latest event per topic for bootstrap snapshots
          if (topicKey !== "sim") {
            cacheLatestEvent(topicKey, event);
          }

          fanOut(topicKey, event);
        } catch {
          // Log parse errors but don't crash the consumer
          console.error(`[Kafka] Failed to parse message from ${topic}`);
        }
      },
    });

    console.log(`[Kafka] Subscribed to ${ALL_TOPICS.length} topics`);
  } catch (err) {
    console.error("[Kafka] Failed to start consumer:", err);
    if (consumer === next) {
      consumer = null;
      connected = false;
    }
    await next.disconnect().catch(disconnectError => console.error("[Kafka] Disconnect failed:", disconnectError));
    scheduleRetry();
  }
}

export async function shutdownKafka(): Promise<void> {
  stopping = true;
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  const current = consumer;
  consumer = null;
  connected = false;
  lastHeartbeatAt = null;
  if (current) await current.disconnect();
}
