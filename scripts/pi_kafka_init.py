"""Create the Pi topic catalogue in one bounded Kafka admin operation."""
from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

TOPICS = (
    "sim.clock", "flights.events", "flights.schedule", "passengers.events",
    "baggage.events", "weather.events", "incidents.events", "incidents.alerts",
    "incidents.inject", "ground.events", "analysis.events", "cost.events",
    "flights.commands", "passengers.commands", "baggage.commands",
)
admin = AdminClient({"bootstrap.servers": "kafka:9092"})
futures = admin.create_topics([NewTopic(topic, 1, 1) for topic in TOPICS], request_timeout=30)
for topic, future in futures.items():
    try:
        future.result(timeout=35)
    except KafkaException as exc:
        if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise
print(f"Kafka: all {len(TOPICS)} topics ready")
