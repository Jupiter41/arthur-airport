"""METAR and TAF string generation from weather parameters."""

from datetime import datetime, timedelta

from services.parameters import WeatherParams


def _fmt_temp(t: float) -> str:
    """Format temperature for METAR (M prefix for negative)."""
    if t < 0:
        return f"M{abs(int(t)):02d}"
    return f"{int(t):02d}"


def build_metar(params: WeatherParams, sim_time: datetime, station_icao: str = "KART") -> str:
    """Build a METAR string from weather parameters and simulation time.

    Format:
        KART {day}{hour}{minute}Z {wind} {vis/cloud} {temp}/{dewpoint} Q{qnh}
    """
    day = sim_time.day
    hour = sim_time.hour
    minute = sim_time.minute

    # Wind
    wind = f"{params.wind_direction:03d}{params.wind_speed_kt:02d}"
    if params.wind_gust_kt > 0:
        wind += f"G{params.wind_gust_kt:02d}"
    wind += "KT"

    # Visibility / CAVOK
    if params.category == "CAVOK":
        vis_cloud = "CAVOK"
    else:
        vis_cloud = f"{params.visibility_m:04d}"
        if params.phenomena:
            vis_cloud += " " + " ".join(params.phenomena)
        if params.ceiling_ft is not None:
            oktas = "BKN" if params.ceiling_ft < 1500 else "OVC"
            hundreds = params.ceiling_ft // 100
            vis_cloud += f" {oktas}{hundreds:03d}"

    # Temp / dewpoint
    temp = f"{_fmt_temp(params.temperature_c)}/{_fmt_temp(params.dew_point_c)}"
    qnh = f"Q{params.qnh_hpa:04d}"

    return f"{station_icao} {day:02d}{hour:02d}{minute:02d}Z {wind} {vis_cloud} {temp} {qnh}"


def build_taf(
    params: WeatherParams,
    sim_time: datetime,
    next_category: str | None = None,
    station_icao: str = "KART",
) -> str:
    """Build a simplified TAF from current weather parameters.

    Generates a 6-hour TAF with optional TEMPO/BECMG groups based on
    transition likelihood.
    """
    day = sim_time.day
    hour = sim_time.hour
    valid_from = f"{day:02d}{hour:02d}"
    valid_to_time = sim_time + timedelta(hours=6)
    valid_to = f"{valid_to_time.day:02d}{valid_to_time.hour:02d}"

    # Wind
    wind = f"{params.wind_direction:03d}{params.wind_speed_kt:02d}"
    if params.wind_gust_kt > 0:
        wind += f"G{params.wind_gust_kt:02d}"
    wind += "KT"

    # Visibility
    if params.category == "CAVOK":
        vis = "CAVOK"
    else:
        vis = f"{params.visibility_m:04d}"
        if params.phenomena:
            vis += " " + " ".join(params.phenomena)
        if params.ceiling_ft is not None:
            oktas = "BKN" if params.ceiling_ft < 1500 else "OVC"
            hundreds = params.ceiling_ft // 100
            vis += f" {oktas}{hundreds:03d}"

    issue_time = f"{day:02d}{hour:02d}00"
    lines = [f"TAF {station_icao} {issue_time}Z {valid_from}/{valid_to} {wind} {vis}"]

    # TEMPO group: degraded conditions within forecast period
    if params.category in ("CAVOK", "VMC"):
        tempo_from = sim_time + timedelta(hours=2)
        tempo_to = sim_time + timedelta(hours=4)
        tempo_vis = "5000 -RA FEW025" if params.category == "CAVOK" else "3000 RA BKN015"
        lines.append(
            f"    TEMPO {tempo_from.day:02d}{tempo_from.hour:02d}/"
            f"{tempo_to.day:02d}{tempo_to.hour:02d} {tempo_vis}"
        )
    elif params.category in ("IMC", "LIFR"):
        tempo_from = sim_time + timedelta(hours=1)
        tempo_to = sim_time + timedelta(hours=3)
        gust = params.wind_gust_kt if params.wind_gust_kt > 0 else params.wind_speed_kt + 15
        tempo_wind = f"{params.wind_direction:03d}{params.wind_speed_kt + 10:02d}G{gust:02d}KT"
        tempo_vis = f"{max(100, params.visibility_m - 500):04d} +RA BKN005"
        lines.append(
            f"    TEMPO {tempo_from.day:02d}{tempo_from.hour:02d}/"
            f"{tempo_to.day:02d}{tempo_to.hour:02d} {tempo_wind} {tempo_vis}"
        )

    # BECMG group: improving or deteriorating trend
    if next_category and next_category != params.category:
        becmg_from = sim_time + timedelta(hours=4)
        becmg_to = sim_time + timedelta(hours=6)
        if next_category in ("CAVOK", "VMC"):
            becmg_vis = "9999 FEW030"
        else:
            becmg_vis = "3000 OVC010"
        lines.append(
            f"    BECMG {becmg_from.day:02d}{becmg_from.hour:02d}/"
            f"{becmg_to.day:02d}{becmg_to.hour:02d} {becmg_vis}"
        )

    return "\n".join(lines)
