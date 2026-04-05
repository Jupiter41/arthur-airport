"""Unit tests for Phase 5 — live METAR fetch and parsing."""

from unittest.mock import MagicMock, patch

from tests.conftest import import_service_module

_live = import_service_module("weather", "services.live_metar")
LiveMetarSource = _live.LiveMetarSource
_parse_metar_json = _live._parse_metar_json
_classify_category = _live._classify_category

# ── Fixture: sample API JSON ──────────────────────────────────

SAMPLE_METAR_JSON = {
    "icaoId": "EGLL",
    "rawOb": "EGLL 010920Z 27012KT 9999 FEW030 BKN040 08/06 Q1013",
    "temp": 8.0,
    "dewp": 6.0,
    "wdir": 270,
    "wspd": 12,
    "wgst": None,
    "visib": "9999",
    "altim": 1013.0,
    "clouds": [
        {"cover": "FEW", "base": 3000},
        {"cover": "BKN", "base": 4000},
    ],
    "wxString": None,
}

SAMPLE_BAD_WEATHER_JSON = {
    "icaoId": "EGLL",
    "rawOb": "EGLL 011000Z 30025G35KT 0800 TSRA OVC002 05/04 Q989",
    "temp": 5.0,
    "dewp": 4.0,
    "wdir": 300,
    "wspd": 25,
    "wgst": 35,
    "visib": "800",
    "altim": 989.0,
    "clouds": [{"cover": "OVC", "base": 200}],
    "wxString": "TS RA",
}


# ── _parse_metar_json tests ───────────────────────────────────

class TestParseMetarJson:
    """Tests for parsing Aviation Weather Center JSON responses."""

    def test_basic_parse(self):
        result = _parse_metar_json(SAMPLE_METAR_JSON)
        assert result is not None
        params, raw = result
        assert raw.startswith("EGLL")
        assert params.temperature_c == 8.0
        assert params.dew_point_c == 6.0
        assert params.wind_direction == 270
        assert params.wind_speed_kt == 12
        assert params.wind_gust_kt == 0
        assert params.qnh_hpa == 1013

    def test_ceiling_from_bkn(self):
        result = _parse_metar_json(SAMPLE_METAR_JSON)
        assert result is not None
        params, _ = result
        # BKN at 4000 ft is ceiling (first BKN/OVC layer)
        assert params.ceiling_ft == 4000

    def test_category_from_good_weather(self):
        result = _parse_metar_json(SAMPLE_METAR_JSON)
        assert result is not None
        params, _ = result
        # vis=9999m, ceiling=4000ft → VMC (ceiling < 5000)
        assert params.category == "VMC"

    def test_bad_weather_parsing(self):
        result = _parse_metar_json(SAMPLE_BAD_WEATHER_JSON)
        assert result is not None
        params, _ = result
        assert params.wind_gust_kt == 35
        assert params.visibility_m == 800
        assert params.ceiling_ft == 200
        assert params.category == "LIFR"
        assert "TS" in params.phenomena
        assert "RA" in params.phenomena

    def test_empty_dict_returns_params(self):
        """Parsing an empty-ish dict should still return defaults."""
        result = _parse_metar_json({"temp": 15, "dewp": 10})
        assert result is not None
        params, _ = result
        # default vis 9999 < 10000, no ceiling → VMC
        assert params.category == "VMC"

    def test_invalid_data_returns_none(self):
        """Non-numeric data that can't be parsed returns None."""
        result = _parse_metar_json({"temp": "not-a-number"})
        assert result is None


# ── LiveMetarSource tests ─────────────────────────────────────

def _mock_httpx_client(json_data):
    """Create a mock httpx.Client context manager returning given JSON."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp
    return mock_client


class TestLiveMetarSource:
    """Tests for the live METAR fetcher with mocked HTTP."""

    def test_icao_uppercase(self):
        source = LiveMetarSource("egll")
        assert source.icao == "EGLL"

    def test_fetch_success(self):
        """Successful HTTP fetch returns parsed params."""
        mock_client = _mock_httpx_client([SAMPLE_METAR_JSON])
        with patch.object(_live.httpx, "Client", return_value=mock_client):
            source = LiveMetarSource("EGLL")
            result = source.fetch()
            assert result is not None
            params, raw = result
            assert params.temperature_c == 8.0
            assert "EGLL" in raw

    def test_fetch_caches(self):
        """Second fetch within TTL returns cached value."""
        mock_client = _mock_httpx_client([SAMPLE_METAR_JSON])
        with patch.object(_live.httpx, "Client", return_value=mock_client):
            source = LiveMetarSource("EGLL")
            result1 = source.fetch()
            result2 = source.fetch()
            assert result1 is not None and result2 is not None
            # HTTP client context entered only once (cached on second call)
            assert mock_client.__enter__.call_count == 1

    def test_fetch_failure_returns_stale(self):
        """On failure, return stale cache."""
        mock_client = _mock_httpx_client([SAMPLE_METAR_JSON])
        with patch.object(_live.httpx, "Client", return_value=mock_client):
            source = LiveMetarSource("EGLL")
            source.fetch()  # populate cache

        # Expire cache
        source._cache_time = 0.0

        # Second call: HTTP failure
        fail_client = MagicMock()
        fail_client.__enter__ = MagicMock(return_value=fail_client)
        fail_client.__exit__ = MagicMock(return_value=False)
        fail_client.get.side_effect = Exception("network error")
        with patch.object(_live.httpx, "Client", return_value=fail_client):
            result = source.fetch()
            assert result is not None  # stale cache returned

    def test_fetch_empty_returns_stale(self):
        """Empty API response returns stale cache."""
        mock_client = _mock_httpx_client([])
        with patch.object(_live.httpx, "Client", return_value=mock_client):
            source = LiveMetarSource("EGLL")
            result = source.fetch()
            assert result is None  # no stale cache, no new data
