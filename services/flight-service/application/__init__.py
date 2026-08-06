"""Application layer for flight-service.

The hexagonal seam between the Kafka *adapter* (``kafka/consumer.py`` — all the
I/O: Neo4j reads/writes, event emission, WebSocket broadcast, in-memory state)
and the *pure domain* (``services/state_machine.py`` — the FSM).

Modules here contain **no I/O**: they take plain values (a flight dict, sim
time, availability flags, turnaround readiness) and return decisions. This makes
the transition logic unit-testable without a running Neo4j/Kafka stack. The
adapter gathers the inputs, calls these functions, and performs the effects.
"""
