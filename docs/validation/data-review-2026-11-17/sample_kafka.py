"""Observe retained live traffic without committing or producing messages."""
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from uuid import uuid4
from urllib.request import urlopen

from confluent_kafka import Consumer

duration = int(os.getenv("REVIEW_SAMPLE_SECONDS", "45"))
consumer = Consumer({"bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
                     "group.id": "review-readonly-" + uuid4().hex,
                     "auto.offset.reset": "latest", "enable.auto.commit": False})
topics = ["sim.clock", "flights.events", "passengers.events", "baggage.events",
          "weather.events", "incidents.events", "cost.events"]
consumer.subscribe(topics)
counts, recon = Counter(), Counter()
clock_facts, facts = {}, []
watermarks, examples = [], {}
last_check = 0
start = time.monotonic()
try:
    while time.monotonic() - start < duration:
        message = consumer.poll(0.1)
        if time.monotonic() - last_check >= 5:
            last_check = time.monotonic()
            with urlopen("http://sim-orchestrator:8006/api/v1/sim/status", timeout=5) as response:
                status = json.load(response)
                watermarks.append({k:status.get(k) for k in ["sim_time","paused","watermarks"]})
        if message is None or message.error():
            continue
        event = json.loads(message.value())
        kind = event.get("event_type", "unknown")
        counts[kind] += 1
        at = str(event.get("sim_time", "")).replace("Z", "").replace("+00:00", "")
        produced = datetime.fromisoformat(event["produced_at"]).timestamp()
        broker_ms = message.timestamp()[1]
        if kind == "SimClockTick":
            clock_facts[at] = produced
        facts.append((kind, at, produced, broker_ms / 1000 if broker_ms >= 0 else None))
        payload = event.get("payload", {})
        if kind == "PassengerStatusBatchChanged":
            for group in payload.get("status_groups", []):
                recon["total"] += len(group.get("ids", []))
                if group.get("reconciliation_reason"):
                    recon["reconciliation"] += len(group.get("ids", []))
        if kind not in examples:
            examples[kind] = {"sim_time":at,"payload_keys":list(payload)}
finally:
    consumer.close()

latencies = defaultdict(list)
broker_latencies = defaultdict(list)
for kind, at, produced, broker in facts:
    if at in clock_facts and kind != "SimClockTick":
        latencies[kind].append(produced - clock_facts[at])
    if broker is not None:
        broker_latencies[kind].append(broker - produced)


def summary(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"n":len(values),"min":round(ordered[0],4),"p50":round(ordered[len(values)//2],4),
            "p95":round(ordered[min(len(values)-1,int(len(values)*0.95))],4),"max":round(ordered[-1],4)}


print(json.dumps({"duration_s":duration,"events":dict(counts),"events_per_s":sum(counts.values())/duration,
                  "tick_to_produced_s":{k:summary(v) for k,v in latencies.items()},
                  "produced_to_broker_s":{k:summary(v) for k,v in broker_latencies.items()},
                  "passenger_transitions":dict(recon),"watermarks":watermarks,"examples":examples},indent=2))
