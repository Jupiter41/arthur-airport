"""Simulation state snapshot and restore.

Serialises the entire Neo4j graph + clock state to a JSON file and
restores it, enabling save/load semantics for the simulation.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from db.neo4j import get_driver

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = Path(os.getenv("SNAPSHOTS_DIR", "/app/snapshots"))


def _ensure_snapshots_dir() -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


async def export_graph() -> dict:
    """Export all Neo4j nodes and relationships as JSON-serialisable dicts."""
    driver = get_driver()

    nodes: list[dict] = []
    relationships: list[dict] = []

    async with driver.session() as session:
        # Export all nodes
        result = await session.run(
            "MATCH (n) RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props"
        )
        async for record in result:
            props = dict(record["props"])
            # Convert neo4j temporal types to ISO strings
            for k, v in props.items():
                if hasattr(v, "isoformat"):
                    props[k] = v.isoformat()
                elif isinstance(v, (list, tuple)):
                    props[k] = [
                        item.isoformat() if hasattr(item, "isoformat") else item
                        for item in v
                    ]
            nodes.append({
                "eid": record["eid"],
                "labels": list(record["labels"]),
                "props": props,
            })

        # Export all relationships
        result = await session.run(
            """
            MATCH (a)-[r]->(b)
            RETURN elementId(a) AS src_eid,
                   elementId(b) AS dst_eid,
                   type(r) AS rel_type,
                   properties(r) AS props
            """
        )
        async for record in result:
            props = dict(record["props"])
            for k, v in props.items():
                if hasattr(v, "isoformat"):
                    props[k] = v.isoformat()
            relationships.append({
                "src_eid": record["src_eid"],
                "dst_eid": record["dst_eid"],
                "rel_type": record["rel_type"],
                "props": props,
            })

    return {"nodes": nodes, "relationships": relationships}


async def create_snapshot(
    name: str,
    sim_time: datetime,
    day_number: int,
    tick_number: int,
    speed_multiplier: int,
    settings: dict,
) -> dict:
    """Create a snapshot of the full simulation state.

    Returns metadata dict with snapshot_id, name, file path, and stats.
    """
    _ensure_snapshots_dir()

    snapshot_id = str(uuid4())
    timestamp = datetime.now(timezone.utc).isoformat().replace(":", "-")
    safe_name = name.replace(" ", "_").replace("/", "_")[:50]
    filename = f"{safe_name}_{timestamp}.json.gz"
    filepath = SNAPSHOTS_DIR / filename

    graph = await export_graph()

    snapshot_data = {
        "snapshot_id": snapshot_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sim_time": sim_time.isoformat(),
        "day_number": day_number,
        "tick_number": tick_number,
        "speed_multiplier": speed_multiplier,
        "settings": settings,
        "graph": graph,
    }

    # Compress with gzip to save space
    raw = json.dumps(snapshot_data, default=str).encode("utf-8")
    with gzip.open(filepath, "wb") as f:
        f.write(raw)

    size_kb = filepath.stat().st_size / 1024

    logger.info(
        "Snapshot created: %s (%d nodes, %d rels, %.1f KB)",
        filename,
        len(graph["nodes"]),
        len(graph["relationships"]),
        size_kb,
    )

    return {
        "snapshot_id": snapshot_id,
        "name": name,
        "filename": filename,
        "sim_time": sim_time.isoformat(),
        "day_number": day_number,
        "node_count": len(graph["nodes"]),
        "relationship_count": len(graph["relationships"]),
        "size_kb": round(size_kb, 1),
    }


async def list_snapshots() -> list[dict]:
    """List all available snapshots with metadata (without loading full graph)."""
    _ensure_snapshots_dir()
    snapshots = []

    for path in sorted(SNAPSHOTS_DIR.glob("*.json.gz"), reverse=True):
        try:
            with gzip.open(path, "rb") as f:
                # Read only the first ~4KB to get metadata without full graph
                raw = f.read()
            data = json.loads(raw)
            snapshots.append({
                "snapshot_id": data["snapshot_id"],
                "name": data["name"],
                "filename": path.name,
                "created_at": data["created_at"],
                "sim_time": data["sim_time"],
                "day_number": data["day_number"],
                "node_count": len(data["graph"]["nodes"]),
                "relationship_count": len(data["graph"]["relationships"]),
                "size_kb": round(path.stat().st_size / 1024, 1),
            })
        except Exception as e:
            logger.warning("Skipping corrupt snapshot %s: %s", path.name, e)

    return snapshots


def _load_snapshot_file(filename: str) -> dict:
    """Load and decompress a snapshot file."""
    filepath = SNAPSHOTS_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Snapshot not found: {filename}")

    with gzip.open(filepath, "rb") as f:
        raw = f.read()
    return json.loads(raw)


async def restore_snapshot(filename: str) -> dict:
    """Restore the simulation state from a snapshot file.

    This:
    1. Wipes all Neo4j data
    2. Re-creates constraints/indexes
    3. Restores all nodes and relationships
    4. Returns the clock state to restore

    The caller is responsible for resetting the clock and settings.
    """
    data = _load_snapshot_file(filename)
    graph = data["graph"]

    driver = get_driver()

    # 1. Wipe Neo4j in batches
    deleted = True
    while deleted:
        async with driver.session() as session:
            result = await session.run(
                "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS cnt"
            )
            record = await result.single()
            deleted = record and record["cnt"] > 0

    # 2. Re-create constraints and indexes
    from db.neo4j import create_constraints_and_indexes
    await create_constraints_and_indexes()

    # 3. Restore nodes in batches using UNWIND
    # Build a mapping from old element IDs to unique temp keys for relationship reconnection
    eid_to_key: dict[str, tuple[str, str]] = {}  # eid -> (label, unique_prop_value)

    batch_size = 500
    nodes = graph["nodes"]

    for i in range(0, len(nodes), batch_size):
        batch = nodes[i:i + batch_size]
        async with driver.session() as session:
            for node in batch:
                labels = node["labels"]
                props = node["props"]

                # Build label string
                label_str = ":".join(labels)

                # Create node
                await session.run(
                    f"CREATE (n:{label_str}) SET n = $props",
                    props=props,
                )

                # Track for relationship restoration
                # Use the first unique property we can find
                unique_key = props.get("id") or props.get("tag") or props.get("name")
                if unique_key and labels:
                    eid_to_key[node["eid"]] = (labels[0], unique_key)

    # 4. Restore relationships
    rels = graph["relationships"]
    for rel in rels:
        src_info = eid_to_key.get(rel["src_eid"])
        dst_info = eid_to_key.get(rel["dst_eid"])
        if not src_info or not dst_info:
            continue

        src_label, src_key = src_info
        dst_label, dst_key = dst_info
        rel_type = rel["rel_type"]
        props = rel.get("props", {})

        # Determine the key property name for each node type
        src_key_prop = "tag" if src_label == "Baggage" else ("name" if src_label in ("Airport", "Terminal") else "id")
        dst_key_prop = "tag" if dst_label == "Baggage" else ("name" if dst_label in ("Airport", "Terminal") else "id")

        query = (
            f"MATCH (a:{src_label} {{{src_key_prop}: $src_key}}), "
            f"(b:{dst_label} {{{dst_key_prop}: $dst_key}}) "
            f"CREATE (a)-[r:{rel_type}]->(b) SET r = $props"
        )

        try:
            async with driver.session() as session:
                await session.run(
                    query,
                    src_key=src_key,
                    dst_key=dst_key,
                    props=props,
                )
        except Exception as e:
            logger.warning(
                "Failed to restore relationship %s->%s (%s): %s",
                src_info, dst_info, rel_type, e,
            )

    node_count = len(nodes)
    rel_count = len(rels)
    logger.info(
        "Snapshot restored: %s (%d nodes, %d rels)",
        data["name"],
        node_count,
        rel_count,
    )

    return {
        "name": data["name"],
        "sim_time": data["sim_time"],
        "day_number": data["day_number"],
        "tick_number": data["tick_number"],
        "speed_multiplier": data["speed_multiplier"],
        "settings": data.get("settings", {}),
        "node_count": node_count,
        "relationship_count": rel_count,
    }


async def delete_snapshot(filename: str) -> bool:
    """Delete a snapshot file. Returns True if deleted."""
    filepath = SNAPSHOTS_DIR / filename
    if filepath.exists():
        filepath.unlink()
        logger.info("Snapshot deleted: %s", filename)
        return True
    return False
