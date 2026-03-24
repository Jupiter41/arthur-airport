"""Meteorological parameter sampling per weather category."""

import random
from dataclasses import dataclass, field


@dataclass
class WeatherParams:
    category: str
    visibility_m: int
    wind_direction: int
    wind_speed_kt: int
    wind_gust_kt: int
    ceiling_ft: int | None
    temperature_c: float
    dew_point_c: float
    qnh_hpa: int
    phenomena: list[str] = field(default_factory=list)


def sample_params(category: str, rng: random.Random | None = None) -> WeatherParams:
    """Sample meteorological parameters consistent with the given weather category.

    Args:
        category: Weather category (CAVOK, VMC, IMC, LIFR)
        rng: Optional seeded Random instance for determinism

    Returns:
        WeatherParams with all sampled values
    """
    r = rng if rng else random

    match category:
        case "CAVOK":
            return WeatherParams(
                category="CAVOK",
                visibility_m=r.randint(10000, 20000),
                wind_direction=r.randint(0, 359),
                wind_speed_kt=r.randint(0, 15),
                wind_gust_kt=0,
                ceiling_ft=None,
                temperature_c=round(r.uniform(10, 25), 1),
                dew_point_c=round(r.uniform(5, 15), 1),
                qnh_hpa=r.randint(1005, 1025),
                phenomena=[],
            )
        case "VMC":
            return WeatherParams(
                category="VMC",
                visibility_m=r.randint(5000, 10000),
                wind_direction=r.randint(0, 359),
                wind_speed_kt=r.randint(5, 25),
                wind_gust_kt=r.choice([0, 0, 0, r.randint(15, 30)]),
                ceiling_ft=r.randint(2000, 5000),
                temperature_c=round(r.uniform(8, 20), 1),
                dew_point_c=round(r.uniform(4, 12), 1),
                qnh_hpa=r.randint(1000, 1022),
                phenomena=r.choices(
                    [[], ["FEW"], ["SCT"]], weights=[0.6, 0.3, 0.1]
                )[0],
            )
        case "IMC":
            return WeatherParams(
                category="IMC",
                visibility_m=r.randint(1500, 5000),
                wind_direction=r.randint(0, 359),
                wind_speed_kt=r.randint(15, 35),
                wind_gust_kt=r.randint(20, 45),
                ceiling_ft=r.randint(500, 1500),
                temperature_c=round(r.uniform(2, 12), 1),
                dew_point_c=round(r.uniform(0, 8), 1),
                qnh_hpa=r.randint(990, 1010),
                phenomena=r.choices(
                    [["RA"], ["TS", "RA"], ["FG"], ["SN"]],
                    weights=[0.4, 0.3, 0.2, 0.1],
                )[0],
            )
        case "LIFR":
            return WeatherParams(
                category="LIFR",
                visibility_m=r.randint(100, 1500),
                wind_direction=r.randint(0, 359),
                wind_speed_kt=r.randint(25, 55),
                wind_gust_kt=r.randint(35, 65),
                ceiling_ft=r.randint(50, 500),
                temperature_c=round(r.uniform(-5, 5), 1),
                dew_point_c=round(r.uniform(-7, 3), 1),
                qnh_hpa=r.randint(978, 998),
                phenomena=r.choices(
                    [["TS", "HVY RA"], ["FG"], ["SN", "BLSN"]],
                    weights=[0.5, 0.3, 0.2],
                )[0],
            )
        case _:
            raise ValueError(f"Unknown weather category: {category}")
