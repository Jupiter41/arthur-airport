"""Neo4j aggregation queries for cost reporting."""

import logging

from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


async def daily_pnl(driver: AsyncDriver, sim_day: int) -> dict:
    """Full P&L for a given simulated day."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:CostRecord {sim_day: $day})
            RETURN c.is_revenue AS is_revenue, c.category AS category,
                   sum(c.amount_eur) AS total, count(c) AS count
            ORDER BY c.is_revenue, total DESC
            """,
            day=sim_day,
        )
        costs: list[dict] = []
        revenues: list[dict] = []
        async for r in result:
            entry = {"category": r["category"], "total": r["total"], "count": r["count"]}
            if r["is_revenue"]:
                revenues.append(entry)
            else:
                costs.append(entry)
        total_cost = sum(c["total"] for c in costs)
        total_revenue = sum(r["total"] for r in revenues)
        return {
            "sim_day": sim_day,
            "costs": costs,
            "revenues": revenues,
            "total_cost_eur": round(total_cost, 2),
            "total_revenue_eur": round(total_revenue, 2),
            "net_eur": round(total_revenue - total_cost, 2),
        }


async def flight_cost_breakdown(driver: AsyncDriver, flight_id: str) -> dict:
    """All costs and revenues linked to a specific flight."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:CostRecord)-[:FOR_FLIGHT]->(f:Flight {id: $fid})
            RETURN c.category AS category, c.amount_eur AS amount_eur,
                   c.description AS description, c.is_revenue AS is_revenue,
                   c.sim_time AS sim_time
            ORDER BY c.sim_time
            """,
            fid=flight_id,
        )
        items = [dict(r) async for r in result]
        total_cost = sum(i["amount_eur"] for i in items if not i["is_revenue"])
        total_rev = sum(i["amount_eur"] for i in items if i["is_revenue"])
        return {
            "flight_id": flight_id,
            "items": items,
            "total_cost_eur": round(total_cost, 2),
            "total_revenue_eur": round(total_rev, 2),
        }


async def incident_total_cost(driver: AsyncDriver, incident_id: str) -> dict:
    """Direct cost + response cost + EU261 from affected flights."""
    async with driver.session() as session:
        # Direct incident costs
        r1 = await session.run(
            """
            MATCH (c:CostRecord)-[:CAUSED_BY]->(i:Incident {id: $iid})
            RETURN c.category AS category, c.amount_eur AS amount_eur,
                   c.description AS description
            """,
            iid=incident_id,
        )
        direct_items = [dict(r) async for r in r1]

        # EU261 from affected flights
        r2 = await session.run(
            """
            MATCH (i:Incident {id: $iid})-[:AFFECTS]->(f:Flight)
            MATCH (c:CostRecord {category: 'eu261_compensation'})-[:FOR_FLIGHT]->(f)
            RETURN c.amount_eur AS amount_eur, c.description AS description,
                   f.flight_number AS flight_number
            """,
            iid=incident_id,
        )
        eu261_items = [dict(r) async for r in r2]

        direct_total = sum(i["amount_eur"] for i in direct_items)
        eu261_total = sum(i["amount_eur"] for i in eu261_items)
        return {
            "incident_id": incident_id,
            "direct_costs": direct_items,
            "eu261_costs": eu261_items,
            "direct_total_eur": round(direct_total, 2),
            "eu261_total_eur": round(eu261_total, 2),
            "grand_total_eur": round(direct_total + eu261_total, 2),
        }


async def most_expensive_incidents(driver: AsyncDriver, sim_day: int, limit: int = 5) -> list:
    """Rank incidents by total financial impact."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:CostRecord {sim_day: $day})-[:CAUSED_BY]->(i:Incident)
            WITH i, sum(c.amount_eur) AS direct_cost
            OPTIONAL MATCH (i)-[:AFFECTS]->(f:Flight)
            OPTIONAL MATCH (eu:CostRecord {category: 'eu261_compensation'})-[:FOR_FLIGHT]->(f)
            WITH i, direct_cost, coalesce(sum(eu.amount_eur), 0) AS eu261_cost
            RETURN i.id AS id, i.type AS type, i.severity AS severity,
                   direct_cost, eu261_cost,
                   direct_cost + eu261_cost AS total_impact
            ORDER BY total_impact DESC
            LIMIT $limit
            """,
            day=sim_day,
            limit=limit,
        )
        return [dict(r) async for r in result]


async def hourly_cost_curve(driver: AsyncDriver, sim_day: int) -> list:
    """Cost and revenue per simulated hour."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:CostRecord {sim_day: $day})
            WITH c, substring(c.sim_time, 11, 2) AS hour_str
            WITH c, toInteger(hour_str) AS hour
            RETURN hour,
                   sum(CASE WHEN c.is_revenue = false THEN c.amount_eur ELSE 0 END) AS cost,
                   sum(CASE WHEN c.is_revenue = true THEN c.amount_eur ELSE 0 END) AS revenue,
                   count(c) AS records
            ORDER BY hour
            """,
            day=sim_day,
        )
        return [dict(r) async for r in result]


async def terminal_pnl(driver: AsyncDriver, terminal_id: str, sim_day: int) -> dict:
    """P&L breakdown for a specific terminal."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:CostRecord {sim_day: $day})-[:FOR_TERMINAL]->(t:Terminal {id: $tid})
            RETURN c.is_revenue AS is_revenue, c.category AS category,
                   sum(c.amount_eur) AS total
            ORDER BY total DESC
            """,
            day=sim_day,
            tid=terminal_id,
        )
        items = [dict(r) async for r in result]
        total_cost = sum(i["total"] for i in items if not i["is_revenue"])
        total_rev = sum(i["total"] for i in items if i["is_revenue"])
        return {
            "terminal_id": terminal_id,
            "sim_day": sim_day,
            "items": items,
            "total_cost_eur": round(total_cost, 2),
            "total_revenue_eur": round(total_rev, 2),
            "net_eur": round(total_rev - total_cost, 2),
        }
