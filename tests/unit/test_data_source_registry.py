"""Unit tests for the shared data source registry and adapter protocol.

Tests registration, switching, listing, protocol compliance, and edge cases
for the pluggable data source adapter system.
"""

import sys
from pathlib import Path

import pytest

# Add _common to path for direct import
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "services" / "_common"))

from data_sources import (  # noqa: E402
    DataSourceAdapter,
    DataSourceRegistry,
    SimulatedSourceAdapter,
)


# ─── Test adapters ───────────────────────────────────────────────


class StubHistoricalAdapter:
    source_id = "historical"
    label = "Historical CSV Replay"

    def __init__(self):
        self._loaded = False
        self._load_count = 0

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> int:
        self._loaded = True
        self._load_count += 1
        return 42


class StubLiveAdapter:
    source_id = "live"
    label = "Live API Feed"

    @property
    def is_loaded(self) -> bool:
        return True

    def load(self) -> int:
        return 0


class StubFailingAdapter:
    source_id = "failing"
    label = "Failing Source"

    @property
    def is_loaded(self) -> bool:
        return False

    def load(self) -> int:
        raise RuntimeError("Connection failed")


# ─── Protocol compliance ────────────────────────────────────────


class TestProtocolCompliance:
    def test_simulated_adapter_is_protocol(self):
        assert isinstance(SimulatedSourceAdapter(), DataSourceAdapter)

    def test_stub_historical_is_protocol(self):
        assert isinstance(StubHistoricalAdapter(), DataSourceAdapter)

    def test_stub_live_is_protocol(self):
        assert isinstance(StubLiveAdapter(), DataSourceAdapter)


# ─── SimulatedSourceAdapter ─────────────────────────────────────


class TestSimulatedSourceAdapter:
    def test_always_loaded(self):
        adapter = SimulatedSourceAdapter()
        assert adapter.is_loaded is True

    def test_load_returns_zero(self):
        assert SimulatedSourceAdapter().load() == 0

    def test_source_id(self):
        assert SimulatedSourceAdapter().source_id == "simulated"

    def test_label(self):
        assert SimulatedSourceAdapter().label == "Simulation Engine"


# ─── Registry basics ────────────────────────────────────────────


class TestRegistryRegistration:
    def test_register_single_adapter(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        assert len(reg.list_sources()) == 1

    def test_register_multiple_adapters(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(StubHistoricalAdapter())
        reg.register(StubLiveAdapter())
        assert len(reg.list_sources()) == 3

    def test_register_replaces_same_id(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(SimulatedSourceAdapter())  # same source_id
        assert len(reg.list_sources()) == 1


class TestRegistryDefault:
    def test_default_active_source(self):
        reg = DataSourceRegistry("weather", env_var="TEST_DS_NONEXISTENT", default="simulated")
        assert reg.active_source == "simulated"

    def test_default_from_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_DS_SOURCE", "historical")
        reg = DataSourceRegistry("weather", env_var="TEST_DS_SOURCE", default="simulated")
        assert reg.active_source == "historical"

    def test_theme_stored(self):
        reg = DataSourceRegistry("passengers", env_var="TEST_SOURCE", default="simulated")
        assert reg.theme == "passengers"


# ─── Switching ──────────────────────────────────────────────────


class TestRegistrySwitching:
    def test_switch_returns_previous_and_active(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(StubHistoricalAdapter())
        result = reg.switch("historical")
        assert result["previous"] == "simulated"
        assert result["active"] == "historical"
        assert result["theme"] == "weather"

    def test_switch_updates_active(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(StubHistoricalAdapter())
        reg.switch("historical")
        assert reg.active_source == "historical"

    def test_switch_to_unknown_raises(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        with pytest.raises(ValueError, match="Unknown source"):
            reg.switch("nonexistent")

    def test_switch_auto_loads_unloaded_adapter(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        adapter = StubHistoricalAdapter()
        reg.register(adapter)
        assert not adapter.is_loaded
        result = reg.switch("historical")
        assert adapter.is_loaded
        assert result["loaded_count"] == 42

    def test_switch_skips_load_if_already_loaded(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        adapter = StubLiveAdapter()  # is_loaded always True
        reg.register(adapter)
        result = reg.switch("live")
        assert "loaded_count" not in result

    def test_switch_back_and_forth(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(StubHistoricalAdapter())
        reg.switch("historical")
        reg.switch("simulated")
        assert reg.active_source == "simulated"

    def test_switch_to_same_source(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        result = reg.switch("simulated")
        assert result["previous"] == "simulated"
        assert result["active"] == "simulated"


# ─── Adapter retrieval ──────────────────────────────────────────


class TestRegistryAdapterRetrieval:
    def test_get_active_returns_adapter(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        adapter = SimulatedSourceAdapter()
        reg.register(adapter)
        assert reg.get_active() is adapter

    def test_get_active_returns_none_when_not_registered(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="historical")
        assert reg.get_active() is None

    def test_get_adapter_by_id(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        adapter = StubHistoricalAdapter()
        reg.register(adapter)
        assert reg.get_adapter("historical") is adapter

    def test_get_adapter_unknown_returns_none(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        assert reg.get_adapter("unknown") is None


# ─── Listing ────────────────────────────────────────────────────


class TestRegistryListing:
    def test_list_sources_shape(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(StubHistoricalAdapter())
        sources = reg.list_sources()
        assert len(sources) == 2
        for src in sources:
            assert "id" in src
            assert "label" in src
            assert "is_loaded" in src
            assert "active" in src

    def test_active_flag_correct(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(StubHistoricalAdapter())
        sources = {s["id"]: s for s in reg.list_sources()}
        assert sources["simulated"]["active"] is True
        assert sources["historical"]["active"] is False

    def test_active_flag_updates_on_switch(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(StubHistoricalAdapter())
        reg.switch("historical")
        sources = {s["id"]: s for s in reg.list_sources()}
        assert sources["simulated"]["active"] is False
        assert sources["historical"]["active"] is True


# ─── Info ───────────────────────────────────────────────────────


class TestRegistryInfo:
    def test_info_shape(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        info = reg.info()
        assert info["theme"] == "weather"
        assert info["active_source"] == "simulated"
        assert info["active_label"] == "Simulation Engine"
        assert isinstance(info["available"], list)

    def test_info_unknown_active_label(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="nonexistent")
        info = reg.info()
        assert info["active_label"] == "unknown"


# ─── Error handling ─────────────────────────────────────────────


class TestRegistryErrors:
    def test_switch_to_failing_adapter_propagates(self):
        """If an adapter's load() raises, the error propagates and source doesn't change."""
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        reg.register(SimulatedSourceAdapter())
        reg.register(StubFailingAdapter())
        with pytest.raises(RuntimeError, match="Connection failed"):
            reg.switch("failing")
        # Active source should NOT have changed
        assert reg.active_source == "simulated"

    def test_empty_registry_list_sources(self):
        reg = DataSourceRegistry("weather", env_var="TEST_SOURCE", default="simulated")
        assert reg.list_sources() == []
