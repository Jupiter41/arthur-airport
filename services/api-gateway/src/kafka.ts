import { Kafka, Consumer, EachMessagePayload } from "kafkajs";
import { fanOut, setCurrentSimTime } from "./websocket";

const TOPIC_KEY_MAP: Record<string, string> = {
  "sim.clock": "sim",
  "flights.events": "flights",
  "passengers.events": "passengers",
  "baggage.events": "baggage",
  "weather.events": "weather",
  "incidents.events": "incidents",
  "incidents.alerts": "alerts",
};

const ALL_TOPICS = Object.keys(TOPIC_KEY_MAP);

let consumer: Consumer | null = null;
let connected = false;

export function isKafkaConnected(): boolean {
  return connected;
}

export async function setupKafka(): Promise<void> {
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

  consumer = kafka.consumer({ groupId });

  try {
    await consumer.connect();
    connected = true;
    console.log("[Kafka] Consumer connected");

    await consumer.subscribe({ topics: ALL_TOPICS, fromBeginning: false });

    await consumer.run({
      eachMessage: async ({ topic, message }: EachMessagePayload) => {
        try {
          const value = message.value?.toString();
          if (!value) return;

          const event = JSON.parse(value);
          const topicKey = TOPIC_KEY_MAP[topic] ?? topic;

          // Cache sim_time from clock ticks
          if (event.event_type === "SimClockTick" && event.payload?.sim_time) {
            setCurrentSimTime(event.payload.sim_time);
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
    connected = false;
  }

  // Handle disconnect events
  consumer.on("consumer.disconnect", () => {
    connected = false;
    console.warn("[Kafka] Consumer disconnected");
  });

  consumer.on("consumer.connect", () => {
    connected = true;
  });
}

export async function shutdownKafka(): Promise<void> {
  if (consumer) {
    await consumer.disconnect();
    connected = false;
  }
}
