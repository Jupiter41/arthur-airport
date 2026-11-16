/**
 * RC9 — WebSocket UI delivery policy.
 *
 * The browser stream is a UI protocol, not a Kafka mirror: each event type is
 * delivered immediately, coalesced to its latest envelope, coalesced as a
 * payload-free refetch hint, or dropped. See api-gateway SPEC §5.
 */
import policy from "./wsDeliveryPolicy.json";

export type DeliveryClass = "immediate" | "latest" | "hint";

const CLASS_BY_TYPE = new Map<string, DeliveryClass>();
for (const cls of ["immediate", "latest", "hint"] as const) {
  for (const type of policy[cls]) CLASS_BY_TYPE.set(type, cls);
}

export function deliveryClass(eventType: string | undefined): DeliveryClass | null {
  return eventType ? CLASS_BY_TYPE.get(eventType) ?? null : null;
}

interface Envelope {
  event_type?: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

/** Key under which a coalesced envelope replaces older ones. */
export function coalesceKey(topicKey: string, event: Envelope): string {
  const terminal = event.payload?.terminal;
  const suffix = event.event_type === "SecurityQueueUpdated" && typeof terminal === "string" ? `:${terminal}` : "";
  return `${topicKey}:${event.event_type}${suffix}`;
}

/** Payload-free refetch hint carrying how many batches it stands for. */
export function toHint(event: Envelope, coalesced: number): Envelope {
  return { ...event, payload: { hint: true, coalesced } };
}

interface Pending {
  topicKey: string;
  event: Envelope;
  count: number;
  cls: DeliveryClass;
}

/**
 * Keeps the newest envelope per coalesce key and flushes them together at most
 * once per window. ``send`` receives the envelope to deliver (hints already
 * stripped); ``onReplaced`` counts superseded envelopes.
 */
export class Coalescer {
  private pending = new Map<string, Pending>();
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly windowMs: number,
    private readonly send: (topicKey: string, event: Envelope) => void,
    private readonly onReplaced: () => void = () => undefined,
  ) {}

  offer(topicKey: string, event: Envelope, cls: DeliveryClass): void {
    const key = coalesceKey(topicKey, event);
    const previous = this.pending.get(key);
    if (previous) this.onReplaced();
    this.pending.set(key, { topicKey, event, cls, count: (previous?.count ?? 0) + 1 });
    if (!this.timer) {
      this.timer = setTimeout(() => this.flush(), this.windowMs);
      this.timer.unref?.();
    }
  }

  flush(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const batch = [...this.pending.values()];
    this.pending.clear();
    for (const item of batch) {
      this.send(item.topicKey, item.cls === "hint" ? toHint(item.event, item.count) : item.event);
    }
  }

  get size(): number {
    return this.pending.size;
  }
}
