"""Eurocontrol STATFOR demand adapter.

Provides long-term traffic growth forecasts (7-year outlook) from Eurocontrol
STATFOR data. Published annually as free download from:
https://www.eurocontrol.int/publication/eurocontrol-forecast-2024-2030

This adapter uses growth rates from STATFOR to project future demand from a
baseline. Three scenarios: base, low, high growth.
"""

from __future__ import annotations

from datetime import date

from .base import AbstractAdapter


class EurocontrolDemandAdapter(AbstractAdapter):
    """Adapter using Eurocontrol STATFOR growth forecasts."""

    # CAGR values from STATFOR 2024–2030 forecast (ECAC region)
    GROWTH_SCENARIOS: dict[str, float] = {
        "base": 0.034,  # 3.4% annual growth
        "low": 0.018,   # 1.8% conservative
        "high": 0.048,  # 4.8% optimistic
    }

    def __init__(self, base_year_pax: int = 30_000_000, scenario: str = "base"):
        """Initialise with a base year passenger total and growth scenario.

        Args:
            base_year_pax: Total annual passengers in the baseline year.
            scenario: One of 'base', 'low', 'high'.
        """
        if scenario not in self.GROWTH_SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}. Must be one of {list(self.GROWTH_SCENARIOS.keys())}")
        self._base_pax = base_year_pax
        self._scenario = scenario
        self._rate = self.GROWTH_SCENARIOS[scenario]

    @property
    def source_name(self) -> str:
        return f"Eurocontrol STATFOR ({self._scenario})"

    @property
    def is_real_data(self) -> bool:
        return True

    def get_demand_growth_rate(self, scenario: str | None = None) -> float:
        """Annual compound growth rate for a planning scenario."""
        s = scenario or self._scenario
        return self.GROWTH_SCENARIOS.get(s, self._rate)

    def project_annual_pax(self, base_year_pax: int | None = None, years_ahead: int = 1, scenario: str | None = None) -> int:
        """Project annual passengers N years ahead using CAGR."""
        base = base_year_pax or self._base_pax
        rate = self.get_demand_growth_rate(scenario)
        return int(base * (1 + rate) ** years_ahead)

    def project_daily_demand(self, years_ahead: int = 0) -> float:
        """Project average daily passengers from base year."""
        annual = self.project_annual_pax(years_ahead=years_ahead)
        return round(annual / 365.0, 1)

    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        """Eurocontrol does not provide flight-level schedules.

        Use a schedule-specific adapter (simulation or BTS) for schedules.
        """
        return []

    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        """Eurocontrol does not provide weather data."""
        return []

    def get_passenger_demand(self, origin: str, destination: str, month: int) -> float:
        """Return projected daily demand scaled by seasonal factor.

        This is a rough proxy — Eurocontrol provides aggregate growth rates,
        not per-route demand. For route-level data, use the BTS adapter.
        """
        import math
        # Seasonal curve: summer peak, winter trough
        seasonal = 1.0 + 0.3 * math.sin((month - 3) * math.pi / 6)
        daily_total = self.project_daily_demand()
        # Spread across ~500 routes as rough estimate
        return round(daily_total / 500 * seasonal, 1)

    def get_growth_table(self, years: int = 10) -> list[dict]:
        """Generate a multi-year growth projection table.

        Useful for the planning dashboard to show long-term capacity needs.
        """
        table: list[dict] = []
        for y in range(years + 1):
            row = {"year_offset": y}
            for scenario in self.GROWTH_SCENARIOS:
                pax = self.project_annual_pax(years_ahead=y, scenario=scenario)
                row[f"pax_{scenario}"] = pax
            table.append(row)
        return table
