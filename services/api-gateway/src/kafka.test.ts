import { afterEach, beforeEach, it, mock } from "node:test";
import assert from "node:assert/strict";
import { Kafka, Consumer } from "kafkajs";
import { setupKafka, shutdownKafka, isKafkaConnected, isKafkaFresh, getLastMessageAt } from "./kafka";

type Listener = (event: { payload: { restart: boolean } }) => void;

class FakeConsumer {
  events = { GROUP_JOIN: "join", HEARTBEAT: "heartbeat", DISCONNECT: "disconnect", CRASH: "crash" };
  listeners = new Map<string, Listener>();
  disconnected = false;
  failSubscribe = false;
  async connect(): Promise<void> { /* transport connection precedes membership */ }
  async subscribe(): Promise<void> {
    if (this.failSubscribe) throw new Error("UNKNOWN_TOPIC_OR_PARTITION");
  }
  async run(): Promise<void> { this.emit("join"); }
  async disconnect(): Promise<void> { this.disconnected = true; this.emit("disconnect"); }
  on(event: string, listener: Listener): void { this.listeners.set(event, listener); }
  emit(event: string, restart = false): void { this.listeners.get(event)?.({ payload: { restart } }); }
}

let attempts: FakeConsumer[];
beforeEach(() => {
  attempts = [];
  mock.timers.enable({ apis: ["setTimeout"] });
  mock.method(Kafka.prototype, "consumer", () => {
    const next = new FakeConsumer();
    attempts.push(next);
    return next as unknown as Consumer;
  });
});
afterEach(async () => { await shutdownKafka(); mock.timers.reset(); mock.restoreAll(); });

async function retry(): Promise<void> {
  mock.timers.tick(1000);
  await new Promise<void>(resolve => setImmediate(resolve));
}

it("replaces a failed subscription and restores readiness after broker recovery", async () => {
  mock.restoreAll();
  mock.method(Kafka.prototype, "consumer", () => {
    const next = new FakeConsumer();
    next.failSubscribe = attempts.length === 0;
    attempts.push(next);
    return next as unknown as Consumer;
  });
  await setupKafka();
  assert.equal(isKafkaConnected(), false);
  assert.equal(attempts[0].disconnected, true);
  await retry();
  assert.equal(attempts.length, 2);
  assert.equal(isKafkaConnected(), true);
  assert.equal(isKafkaFresh(), true);
});

it("replaces a non-restarting crash but leaves KafkaJS runtime retries single-owned", async () => {
  await Promise.all([setupKafka(), setupKafka()]);
  assert.equal(attempts.length, 1);
  attempts[0].emit("crash", true);
  await retry();
  assert.equal(attempts.length, 1);
  attempts[0].emit("join");
  attempts[0].emit("crash", false);
  await retry();
  assert.equal(attempts.length, 2);
  assert.equal(attempts[0].disconnected, true);
  assert.equal(isKafkaConnected(), true);
});

it("heartbeats keep paused-clock readiness fresh without inventing messages", async () => {
  let now = 100000;
  mock.method(Date, "now", () => now);
  await setupKafka();
  const lastMessage = getLastMessageAt();
  now += 40000;
  assert.equal(isKafkaFresh(), false);
  attempts[0].emit("heartbeat");
  assert.equal(isKafkaFresh(), true);
  assert.equal(getLastMessageAt(), lastMessage);
});

it("shutdown cancels queued replacement after a crash", async () => {
  await setupKafka();
  attempts[0].emit("crash", false);
  await shutdownKafka();
  await retry();
  assert.equal(attempts.length, 1);
  assert.equal(isKafkaConnected(), false);
});
