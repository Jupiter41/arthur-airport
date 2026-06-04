"""Airport valuation model — EBITDA, revenue waterfall, sensitivity, thesis.

Computes a simple but financially-grounded EBITDA for the airport perspective:

* **Revenue** — every `CostRecord` with `is_revenue = True` (landing fees,
  passenger fees, gate fees, retail spend, slot fees). Categories not present
  in the day's data are zero-filled so the waterfall always has the same shape.
* **Operating expenses (airport-borne)** — only the categories the airport
  actually pays out of pocket: ``staffing`` and the two ``incident_*`` lines.
  Airline-borne costs (`landing_fee`, `passenger_fee`, `gate_fee`, `eu261_*`,
  `holding_fuel`, `ground_handling`) are shown as *pass-through* for context
  but excluded from EBITDA.
* **EBITDA** = ``revenue − airport_opex`` (we do not have D&A/interest in this
  toy model, so EBITDA == operating profit).

Horizons: ``day`` (raw aggregate), ``week`` (×7), ``year`` (×365). All
projections are linear extrapolations of the requested sim-day.
"""

from __future__ import annotations

from typing import Iterable, Literal

import structlog

logger = structlog.get_logger(__name__)

# Categories considered as revenue streams in the waterfall — order matters
# for chart rendering.
REVENUE_STREAMS: list[str] = [
    "landing_fee",
    "passenger_fee",
    "gate_fee",
    "slot_revenue",
    "retail_revenue",
]

# Categories the airport pays itself.
AIRPORT_OPEX_STREAMS: list[str] = [
    "staffing",
    "incident_direct",
    "incident_response",
]

# Categories an airline (or its handling agent) pays — pass-through, shown
# alongside the EBITDA waterfall but excluded from it.
PASS_THROUGH_STREAMS: list[str] = [
    "ground_handling",
    "holding_fuel",
    "eu261_compensation",
]

Horizon = Literal["day", "week", "year"]
HORIZON_MULTIPLIERS: dict[Horizon, int] = {"day": 1, "week": 7, "year": 365}


def _zero_filled(streams: Iterable[str], data: dict[str, float]) -> dict[str, float]:
    return {s: round(float(data.get(s, 0.0)), 2) for s in streams}


def build_ebitda(daily_pnl: dict, horizon: Horizon = "day") -> dict:
    """Build the EBITDA waterfall from a `daily_pnl()` payload.

    Expected input shape (subset of `db.queries.daily_pnl`)::

        {
            "sim_day": int,
            "costs":     [{"category": str, "total": float}, ...],
            "revenues":  [{"category": str, "total": float}, ...],
        }
    """
    if horizon not in HORIZON_MULTIPLIERS:
        raise ValueError(f"unknown horizon: {horizon!r}")

    rev_by_cat: dict[str, float] = {r["category"]: r["total"] for r in daily_pnl.get("revenues", [])}
    cost_by_cat: dict[str, float] = {c["category"]: c["total"] for c in daily_pnl.get("costs", [])}

    revenue_streams = _zero_filled(REVENUE_STREAMS, rev_by_cat)
    opex_streams = _zero_filled(AIRPORT_OPEX_STREAMS, cost_by_cat)
    pass_through = _zero_filled(PASS_THROUGH_STREAMS, cost_by_cat)

    daily_revenue = sum(revenue_streams.values())
    daily_opex = sum(opex_streams.values())
    daily_ebitda = daily_revenue - daily_opex
    margin_pct = round((daily_ebitda / daily_revenue * 100.0) if daily_revenue > 0 else 0.0, 1)

    multiplier = HORIZON_MULTIPLIERS[horizon]
    return {
        "sim_day": daily_pnl.get("sim_day"),
        "horizon": horizon,
        "multiplier_days": multiplier,
        "revenue": {
            "by_stream": revenue_streams,
            "total_eur_daily": round(daily_revenue, 2),
            "total_eur_horizon": round(daily_revenue * multiplier, 2),
        },
        "airport_opex": {
            "by_stream": opex_streams,
            "total_eur_daily": round(daily_opex, 2),
            "total_eur_horizon": round(daily_opex * multiplier, 2),
        },
        "pass_through": {
            "by_stream": pass_through,
            "total_eur_daily": round(sum(pass_through.values()), 2),
            "note": "Airline-borne costs — shown for context, excluded from EBITDA.",
        },
        "ebitda": {
            "daily_eur": round(daily_ebitda, 2),
            "horizon_eur": round(daily_ebitda * multiplier, 2),
            "margin_pct": margin_pct,
        },
    }


# ─── Sensitivity ────────────────────────────────────────────────


def apply_scenario(
    base: dict,
    *,
    demand_growth: float = 0.0,
    fuel_price_pct: float = 0.0,
    eu261_rate_pct: float = 0.0,
) -> dict:
    """Recompute EBITDA under a single sensitivity scenario.

    * ``demand_growth`` scales **all revenue streams** linearly (e.g. 0.05 = +5 %).
    * ``fuel_price_pct`` only affects the ``holding_fuel`` pass-through line —
      not part of EBITDA but reported for transparency.
    * ``eu261_rate_pct`` scales the ``eu261_compensation`` pass-through; same
      caveat as above.

    The base scenario (0,0,0) is a no-op and returns the same numbers as
    `build_ebitda`.
    """
    multiplier = base["multiplier_days"]
    rev = {k: v * (1.0 + demand_growth) for k, v in base["revenue"]["by_stream"].items()}
    opex = dict(base["airport_opex"]["by_stream"])  # airport opex unaffected
    pt = dict(base["pass_through"]["by_stream"])
    if "holding_fuel" in pt:
        pt["holding_fuel"] = pt["holding_fuel"] * (1.0 + fuel_price_pct)
    if "eu261_compensation" in pt:
        pt["eu261_compensation"] = pt["eu261_compensation"] * (1.0 + eu261_rate_pct)

    daily_rev = sum(rev.values())
    daily_opex = sum(opex.values())
    daily_ebitda = daily_rev - daily_opex
    margin_pct = round((daily_ebitda / daily_rev * 100.0) if daily_rev > 0 else 0.0, 1)
    return {
        "scenario": {
            "demand_growth": demand_growth,
            "fuel_price_pct": fuel_price_pct,
            "eu261_rate_pct": eu261_rate_pct,
        },
        "revenue_eur_daily": round(daily_rev, 2),
        "airport_opex_eur_daily": round(daily_opex, 2),
        "pass_through_eur_daily": round(sum(pt.values()), 2),
        "ebitda_daily_eur": round(daily_ebitda, 2),
        "ebitda_horizon_eur": round(daily_ebitda * multiplier, 2),
        "margin_pct": margin_pct,
    }


def run_sensitivity(
    base: dict,
    *,
    demand_growth: list[float],
    fuel_price_pct: list[float],
    eu261_rate_pct: list[float],
) -> list[dict]:
    """Cartesian product over the three input lists. Returns a flat list."""
    out: list[dict] = []
    for dg in demand_growth or [0.0]:
        for fp in fuel_price_pct or [0.0]:
            for eu in eu261_rate_pct or [0.0]:
                out.append(
                    apply_scenario(
                        base,
                        demand_growth=dg,
                        fuel_price_pct=fp,
                        eu261_rate_pct=eu,
                    )
                )
    return out


# ─── Investment thesis (JSON) ───────────────────────────────────


def build_thesis(base: dict, scenarios: list[dict]) -> dict:
    """Render a structured investment-case JSON document.

    The dashboard / a separate PDF renderer can transform this directly into
    a printable document. Intentionally textual — no recommended valuation
    multiplier or DCF here, those belong to the planning-service.
    """
    if not scenarios:
        scenarios = [apply_scenario(base)]

    daily_ebitda_values = sorted(s["ebitda_daily_eur"] for s in scenarios)
    low = daily_ebitda_values[0]
    high = daily_ebitda_values[-1]
    midpoint = sum(daily_ebitda_values) / len(daily_ebitda_values)

    risk_factors: list[str] = []
    if base["airport_opex"]["total_eur_daily"] > base["revenue"]["total_eur_daily"]:
        risk_factors.append(
            "Airport OpEx exceeds revenue at baseline — going-concern risk."
        )
    if base["pass_through"]["by_stream"].get("eu261_compensation", 0.0) > 50_000:
        risk_factors.append(
            "EU261 exposure above €50 k/day — operational reliability is a key valuation driver."
        )
    if base["pass_through"]["by_stream"].get("holding_fuel", 0.0) > 20_000:
        risk_factors.append(
            "Holding-fuel burn elevated — airspace efficiency / ATC capacity is a watch item."
        )
    if not risk_factors:
        risk_factors.append("Baseline operations stable across all monitored signals.")

    return {
        "summary": {
            "sim_day": base["sim_day"],
            "horizon": base["horizon"],
            "baseline_revenue_eur": base["revenue"]["total_eur_horizon"],
            "baseline_opex_eur": base["airport_opex"]["total_eur_horizon"],
            "baseline_ebitda_eur": base["ebitda"]["horizon_eur"],
            "baseline_margin_pct": base["ebitda"]["margin_pct"],
        },
        "ebitda_range_daily_eur": {
            "low": round(low, 2),
            "midpoint": round(midpoint, 2),
            "high": round(high, 2),
        },
        "scenarios": scenarios,
        "risk_factors": risk_factors,
        "investment_recommendation": (
            "Above-cost-of-capital returns under base demand assumptions"
            if midpoint > 0
            else "Negative midpoint EBITDA — material restructuring required before investment thesis can be built"
        ),
    }
