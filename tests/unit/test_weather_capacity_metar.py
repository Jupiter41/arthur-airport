"""Unit tests for weather-service capacity and METAR — pure logic, no I/O."""

import random
from datetime import datetime

import pytest

from tests.conftest import import_service_module

_params = import_service_module("weather", "services.parameters")
WeatherParams = _params.WeatherParams
sample_params = _params.sample_params

_cap = import_service_module("weather", "services.capacity")
compute_runway_capacity = _cap.compute_runway_capacity
compute_impact_summary = _cap.compute_impact_summary

_metar = import_service_module("weather", "services.metar")
build_metar = _metar.build_metar
build_taf = _metar.build_taf


SIM_TIME = datetime(2025, 6, 15, 12, 30, 0)


# ── WeatherParams sampling ──────────────────────────────────────

class TestSampleParams:
    """Verify sampled parameters fall within documented ranges."""

    def test_cavok_visibility_above_10km(self):
        params = sample_params("CAVOK", random.Random(42))
        assert params.visibility_m >= 10000

    def test_lifr_visibility_below_1500m(self):
        params = sample_params("LIFR", random.Random(42))
        assert params.visibility_m <= 1500

    def test_imc_has_phenomena(self):
        params = sample_params("IMC", random.Random(42))
        assert len(params.phenomena) >= 1

    def test_cavok_no_ceiling(self):
        params = sample_params("CAVOK", random.Random(42))
        assert params.ceiling_ft is None

    def test_lifr_low_ceiling(self):
        params = sample_params("LIFR", random.Random(42))
        assert params.ceiling_ft is not None
        assert params.ceiling_ft <= 500

    def test_unknown_category_raises(self):
        with pytest.raises(ValueError, match="Unknown weather category"):
            sample_params("TORNADO")

    def test_deterministic_with_rng(self):
        p1 = sample_params("VMC", random.Random(99))
        p2 = sample_params("VMC", random.Random(99))
        assert p1.visibility_m == p2.visibility_m
        assert p1.wind_speed_kt == p2.wind_speed_kt


# ── Runway capacity ──────────────────────────────────────────────

class TestRunwayCapacity:
    """Verify capacity calculations per weather category."""

    def test_cavok_full_capacity(self):
        params = WeatherParams(
            category="CAVOK", visibility_m=15000, wind_direction=90,
            wind_speed_kt=10, wind_gust_kt=0, ceiling_ft=None,
            temperature_c=20, dew_point_c=10, qnh_hpa=1015,
        )
        cap = compute_runway_capacity(params)
        assert cap["arrival_rate"] == 32
        assert cap["departure_rate"] == 32
        assert cap["ils_required"] is False

    def test_lifr_reduced_capacity(self):
        params = WeatherParams(
            category="LIFR", visibility_m=500, wind_direction=90,
            wind_speed_kt=20, wind_gust_kt=35, ceiling_ft=200,
            temperature_c=2, dew_point_c=0, qnh_hpa=990,
        )
        cap = compute_runway_capacity(params)
        assert cap["arrival_rate"] == 8
        assert cap["departure_rate"] == 6
        assert cap["ils_required"] is True

    def test_imc_with_ils(self):
        params = WeatherParams(
            category="IMC", visibility_m=3000, wind_direction=90,
            wind_speed_kt=20, wind_gust_kt=25, ceiling_ft=1000,
            temperature_c=8, dew_point_c=5, qnh_hpa=1000,
        )
        cap = compute_runway_capacity(params)
        assert cap["ils_required"] is True
        assert cap["active_runways"] == 1

    def test_high_crosswind_reduces_capacity(self):
        params = WeatherParams(
            category="CAVOK", visibility_m=15000, wind_direction=90,
            wind_speed_kt=40, wind_gust_kt=50, ceiling_ft=None,
            temperature_c=20, dew_point_c=10, qnh_hpa=1015,
        )
        cap = compute_runway_capacity(params)
        # 32 * 0.60 = 19
        assert cap["arrival_rate"] < 32
        assert cap["departure_rate"] < 32

    def test_tailwind_reduces_capacity(self):
        params = WeatherParams(
            category="CAVOK", visibility_m=15000, wind_direction=200,
            wind_speed_kt=15, wind_gust_kt=0, ceiling_ft=None,
            temperature_c=20, dew_point_c=10, qnh_hpa=1015,
        )
        cap = compute_runway_capacity(params)
        assert cap["arrival_rate"] < 32


# ── Impact summary ───────────────────────────────────────────────

class TestImpactSummary:
    """Verify impact summary structure."""

    def test_cavok_operations_normal(self):
        params = WeatherParams(
            category="CAVOK", visibility_m=15000, wind_direction=90,
            wind_speed_kt=10, wind_gust_kt=0, ceiling_ft=None,
            temperature_c=20, dew_point_c=10, qnh_hpa=1015,
        )
        cap = compute_runway_capacity(params)
        impact = compute_impact_summary(params, cap)
        assert impact["operations_normal"] is True
        assert impact["severity"] == "none"

    def test_lifr_not_normal(self):
        params = WeatherParams(
            category="LIFR", visibility_m=500, wind_direction=90,
            wind_speed_kt=20, wind_gust_kt=35, ceiling_ft=200,
            temperature_c=2, dew_point_c=0, qnh_hpa=990,
        )
        cap = compute_runway_capacity(params)
        impact = compute_impact_summary(params, cap)
        assert impact["operations_normal"] is False
        assert impact["severity"] == "severe"


# ── METAR builder ────────────────────────────────────────────────

class TestBuildMetar:
    """Verify METAR string format."""

    def test_cavok_metar_format(self):
        params = WeatherParams(
            category="CAVOK", visibility_m=15000, wind_direction=90,
            wind_speed_kt=10, wind_gust_kt=0, ceiling_ft=None,
            temperature_c=20, dew_point_c=10, qnh_hpa=1015,
        )
        metar = build_metar(params, SIM_TIME)
        assert metar.startswith("KART")
        assert "CAVOK" in metar
        assert "09010KT" in metar
        assert "Q1015" in metar

    def test_imc_metar_has_visibility(self):
        params = WeatherParams(
            category="IMC", visibility_m=3000, wind_direction=270,
            wind_speed_kt=25, wind_gust_kt=35, ceiling_ft=800,
            temperature_c=5, dew_point_c=3, qnh_hpa=998,
            phenomena=["RA"],
        )
        metar = build_metar(params, SIM_TIME)
        assert "3000" in metar
        assert "RA" in metar
        assert "G35" in metar

    def test_negative_temperature_m_prefix(self):
        params = WeatherParams(
            category="LIFR", visibility_m=500, wind_direction=90,
            wind_speed_kt=30, wind_gust_kt=45, ceiling_ft=100,
            temperature_c=-3, dew_point_c=-5, qnh_hpa=985,
        )
        metar = build_metar(params, SIM_TIME)
        assert "M03" in metar
        assert "M05" in metar


# ── TAF builder ──────────────────────────────────────────────────

class TestBuildTaf:
    """Verify TAF string format."""

    def test_taf_starts_correctly(self):
        params = WeatherParams(
            category="CAVOK", visibility_m=15000, wind_direction=90,
            wind_speed_kt=10, wind_gust_kt=0, ceiling_ft=None,
            temperature_c=20, dew_point_c=10, qnh_hpa=1015,
        )
        taf = build_taf(params, SIM_TIME)
        assert taf.startswith("TAF KART")

    def test_taf_with_becmg(self):
        params = WeatherParams(
            category="CAVOK", visibility_m=15000, wind_direction=90,
            wind_speed_kt=10, wind_gust_kt=0, ceiling_ft=None,
            temperature_c=20, dew_point_c=10, qnh_hpa=1015,
        )
        taf = build_taf(params, SIM_TIME, next_category="IMC")
        assert "BECMG" in taf
