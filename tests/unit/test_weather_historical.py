"""Unit tests for Phase 5 — historical METAR parsing."""

from datetime import datetime, timedelta

import pytest

from tests.conftest import import_service_module

_historical = import_service_module("weather", "services.historical")
HistoricalMetarSource = _historical.HistoricalMetarSource
_classify_category = _historical._classify_category

# ── Test data ───────────────────────────────────────────────────

SAMPLE_CSV = """station,valid,tmpf,dwpf,relh,drct,sknt,p01i,alti,mslp,vsby,gust,skyc1,skyc2,skyc3,skyc4,skyl1,skyl2,skyl3,skyl4,wxcodes,ice_accretion_1hr,ice_accretion_3hr,ice_accretion_6hr,peak_wind_gust,peak_wind_drct,peak_wind_time,feel,metar,snowdepth
EGLL,2026-02-25 06:00,50.00,48.20,93.50,190.00,5.00,0.00,29.97,M,6.21,M,FEW,M,M,M,1000.00,M,M,M,M,M,M,M,M,M,M,50.00,EGLL 250600Z AUTO 19005KT 9999 FEW010 10/09 Q1015 NOSIG,M
EGLL,2026-02-25 07:00,48.00,46.00,90.00,270.00,15.00,0.00,29.50,M,3.11,M,BKN,M,M,M,800.00,M,M,M,RA,M,M,M,M,M,M,48.00,EGLL 250700Z AUTO 27015KT 5000 RA BKN008 09/08 Q999 NOSIG,M
EGLL,2026-02-25 08:00,41.00,39.00,85.00,300.00,30.00,0.00,29.20,M,0.62,25.00,OVC,M,M,M,300.00,M,M,M,TS RA,M,M,M,M,M,M,41.00,EGLL 250800Z AUTO 30030G25KT 1000 TSRA OVC003 05/04 Q989 NOSIG,M
EGLL,2026-02-25 12:00,55.00,50.00,80.00,180.00,8.00,0.00,30.10,M,9.94,M,SCT,M,M,M,3000.00,M,M,M,M,M,M,M,M,M,M,55.00,EGLL 251200Z AUTO 18008KT CAVOK 13/10 Q1020 NOSIG,M
EGLL,2026-02-26 06:00,52.00,49.00,88.00,200.00,10.00,0.00,30.00,M,6.21,M,FEW,M,M,M,2000.00,M,M,M,M,M,M,M,M,M,M,52.00,EGLL 260600Z AUTO 20010KT 9999 FEW020 11/09 Q1016 NOSIG,M
"""

# ── HistoricalMetarSource tests ────────────────────────────────


class TestHistoricalMetarSource:
    """Tests for the historical METAR CSV parser and replay."""

    @pytest.fixture()
    def csv_file(self, tmp_path):
        """Create a temporary CSV file with sample METAR data."""
        path = tmp_path / "test_metar.csv"
        path.write_text(SAMPLE_CSV.strip(), encoding="utf-8")
        return path

    def test_load_parses_csv(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        count = source.load()
        assert count == 5
        assert source.is_loaded
        assert source.observation_count == 5

    def test_load_missing_file_returns_zero(self, tmp_path):
        source = HistoricalMetarSource(tmp_path / "nonexistent.csv")
        count = source.load()
        assert count == 0
        assert not source.is_loaded

    def test_cavok_classification(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        source.load()
        # The 12:00 observation has vis=9.94 SM (~16km) and ceiling=3000ft → CAVOK
        # Map sim_time to 2026-02-25 12:00
        result = source.get_params_at(datetime(2026, 2, 25, 12, 0))
        assert result is not None
        params, raw = result
        assert params.category == "CAVOK"

    def test_imc_classification(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        source.load()
        # 07:00 observation: vis=3.11 SM (~5km), ceiling=800ft BKN → IMC
        result = source.get_params_at(datetime(2026, 2, 25, 7, 0))
        assert result is not None
        params, raw = result
        assert params.category == "IMC"

    def test_lifr_classification(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        source.load()
        # 08:00 observation: vis=0.62 SM (~1000m), ceiling=300ft OVC → LIFR
        result = source.get_params_at(datetime(2026, 2, 25, 8, 0))
        assert result is not None
        params, raw = result
        assert params.category == "LIFR"

    def test_wind_parsing(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        source.load()
        result = source.get_params_at(datetime(2026, 2, 25, 8, 0))
        assert result is not None
        params, _ = result
        assert params.wind_direction == 300
        assert params.wind_speed_kt == 30
        assert params.wind_gust_kt == 25

    def test_temperature_conversion(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        source.load()
        result = source.get_params_at(datetime(2026, 2, 25, 6, 0))
        assert result is not None
        params, _ = result
        # 50°F = 10°C
        assert abs(params.temperature_c - 10.0) < 0.5

    def test_phenomena_parsing(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        source.load()
        result = source.get_params_at(datetime(2026, 2, 25, 8, 0))
        assert result is not None
        params, _ = result
        assert "TS" in params.phenomena
        assert "RA" in params.phenomena

    def test_cyclic_replay(self, csv_file):
        """Day wrapping: sim day beyond CSV span wraps cyclically."""
        source = HistoricalMetarSource(csv_file)
        source.load()
        span = source.span_days
        # Access a time span_days ahead — should wrap to same data
        base = datetime(2026, 2, 25, 12, 0)
        wrapped = base + timedelta(days=span)
        result_base = source.get_params_at(base)
        result_wrapped = source.get_params_at(wrapped)
        assert result_base is not None and result_wrapped is not None
        assert result_base[0].category == result_wrapped[0].category

    def test_empty_csv_returns_none(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("station,valid,tmpf,dwpf\n", encoding="utf-8")
        source = HistoricalMetarSource(path)
        source.load()
        result = source.get_params_at(datetime(2026, 2, 25, 12, 0))
        assert result is None

    def test_qnh_conversion(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        source.load()
        result = source.get_params_at(datetime(2026, 2, 25, 6, 0))
        assert result is not None
        params, _ = result
        # 29.97 inHg ≈ 1015 hPa
        assert 1013 <= params.qnh_hpa <= 1017

    def test_span_days(self, csv_file):
        source = HistoricalMetarSource(csv_file)
        source.load()
        assert source.span_days == 2  # Feb 25 and Feb 26


# ── IFR classification tests ─────────────────────────────────

class TestIfrClassification:
    """Test the _classify_category function."""

    def test_cavok(self):
        assert _classify_category(15000, 6000) == "CAVOK"

    def test_vmc(self):
        assert _classify_category(7000, 2000) == "VMC"

    def test_imc(self):
        assert _classify_category(3000, 800) == "IMC"

    def test_lifr(self):
        assert _classify_category(1000, 300) == "LIFR"

    def test_no_ceiling_cavok(self):
        assert _classify_category(15000, None) == "CAVOK"

    def test_no_ceiling_imc(self):
        assert _classify_category(3000, None) == "IMC"

    def test_low_vis_overrides_high_ceiling(self):
        assert _classify_category(1000, 5000) == "LIFR"

    def test_low_ceiling_overrides_high_vis(self):
        # 400ft < 500 threshold → LIFR regardless of good visibility
        assert _classify_category(15000, 400) == "LIFR"
