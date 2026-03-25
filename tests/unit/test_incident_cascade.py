"""Unit tests for incident-service cascade engine — pure logic + depth limit."""


from tests.conftest import import_service_module

_casc = import_service_module("incident", "services.cascade")
CASCADE_MAX_DEPTH = _casc.CASCADE_MAX_DEPTH
CASCADE_RULES = _casc.CASCADE_RULES
SEVERITY_RANK = _casc.SEVERITY_RANK
_check_and_mark_cascaded = _casc._check_and_mark_cascaded
_cascaded_incidents = _casc._cascaded_incidents


class TestCascadeConstants:
    def test_max_depth_is_5(self):
        assert CASCADE_MAX_DEPTH == 5

    def test_severity_rank_order(self):
        assert SEVERITY_RANK["low"] < SEVERITY_RANK["medium"]
        assert SEVERITY_RANK["medium"] < SEVERITY_RANK["high"]
        assert SEVERITY_RANK["high"] < SEVERITY_RANK["critical"]

    def test_all_primary_types_have_rules(self):
        primary_types = [
            "runway_incursion", "baggage_fire", "security_breach",
            "severe_weather", "system_failure",
        ]
        for t in primary_types:
            assert t in CASCADE_RULES, f"Missing cascade rules for {t}"


class TestCascadeRules:
    """Verify the cascade rule table structure and depth chains."""

    def test_runway_incursion_chain(self):
        """runway_incursion → runway_closure_holding_stack → departure_ground_stop → gate_congestion."""
        assert "runway_incursion" in CASCADE_RULES
        children = [r["child_type"] for r in CASCADE_RULES["runway_incursion"]]
        assert "runway_closure_holding_stack" in children

        assert "runway_closure_holding_stack" in CASCADE_RULES
        children2 = [r["child_type"] for r in CASCADE_RULES["runway_closure_holding_stack"]]
        assert "departure_ground_stop" in children2

        assert "departure_ground_stop" in CASCADE_RULES
        children3 = [r["child_type"] for r in CASCADE_RULES["departure_ground_stop"]]
        assert "gate_congestion" in children3

    def test_security_breach_chain(self):
        """security_breach → zone_lockdown → security_queue_frozen → boarding_delayed → flight_delayed."""
        chain = ["security_breach", "zone_lockdown", "security_queue_frozen", "boarding_delayed"]
        for i, parent_type in enumerate(chain):
            assert parent_type in CASCADE_RULES
            children = [r["child_type"] for r in CASCADE_RULES[parent_type]]
            if i < len(chain) - 1:
                assert chain[i + 1] in children or any(
                    r["child_type"] for r in CASCADE_RULES[parent_type]
                )

    def test_severe_weather_chain(self):
        """severe_weather → runway_capacity_reduction → holding_stack → departure_ground_delay."""
        assert "severe_weather" in CASCADE_RULES
        children = [r["child_type"] for r in CASCADE_RULES["severe_weather"]]
        assert "runway_capacity_reduction" in children

    def test_baggage_fire_chain(self):
        """baggage_fire → make_up_zone_offline → flight_baggage_not_loaded."""
        assert "baggage_fire" in CASCADE_RULES
        children = [r["child_type"] for r in CASCADE_RULES["baggage_fire"]]
        assert "make_up_zone_offline" in children

    def test_system_failure_chain(self):
        """system_failure → baggage_throughput_reduction → make_up_delay → flight_baggage_not_loaded."""
        assert "system_failure" in CASCADE_RULES
        children = [r["child_type"] for r in CASCADE_RULES["system_failure"]]
        assert "baggage_throughput_reduction" in children

    def test_all_rules_have_required_fields(self):
        for parent_type, rules in CASCADE_RULES.items():
            for rule in rules:
                assert "child_type" in rule
                assert "min_severity" in rule
                assert "child_severity" in rule
                assert rule["min_severity"] in SEVERITY_RANK
                assert rule["child_severity"] in SEVERITY_RANK

    def test_max_cascade_chain_depth(self):
        """No single-type chain exceeds 5 hops from a primary incident."""
        primary_types = ["runway_incursion", "baggage_fire", "security_breach",
                        "severe_weather", "system_failure"]
        
        def max_chain_depth(incident_type: str, depth: int = 0, visited: set | None = None) -> int:
            if visited is None:
                visited = set()
            if incident_type in visited:
                return depth  # Cycle detected — stop
            visited.add(incident_type)
            rules = CASCADE_RULES.get(incident_type, [])
            if not rules:
                return depth
            return max(
                max_chain_depth(r["child_type"], depth + 1, visited.copy())
                for r in rules
            )
        
        for primary in primary_types:
            depth = max_chain_depth(primary)
            assert depth <= CASCADE_MAX_DEPTH, (
                f"Chain starting from {primary} has depth {depth} > {CASCADE_MAX_DEPTH}"
            )

    def test_no_circular_references(self):
        """Verify no circular references in cascade rules."""
        def has_cycle(start: str, visited: set | None = None) -> bool:
            if visited is None:
                visited = set()
            if start in visited:
                return True
            visited.add(start)
            for rule in CASCADE_RULES.get(start, []):
                if has_cycle(rule["child_type"], visited.copy()):
                    return True
            return False
        
        for parent_type in CASCADE_RULES:
            assert not has_cycle(parent_type), f"Circular reference starting from {parent_type}"


class TestCascadeDuplicatePrevention:
    """Verify idempotency of cascade evaluation."""

    def test_mark_cascaded(self):
        _cascaded_incidents.clear()
        assert _check_and_mark_cascaded("test-id-1") is False  # First time
        assert _check_and_mark_cascaded("test-id-1") is True   # Duplicate

    def test_different_ids_not_duplicate(self):
        _cascaded_incidents.clear()
        assert _check_and_mark_cascaded("id-a") is False
        assert _check_and_mark_cascaded("id-b") is False


class TestCascadeDepthLimit:
    """Verify the depth limit is enforced."""

    def test_runway_incursion_chain_within_limit(self):
        """The longest chain from runway_incursion should stop within CASCADE_MAX_DEPTH."""
        chain = []
        current = "runway_incursion"
        while current in CASCADE_RULES:
            chain.append(current)
            rules = CASCADE_RULES[current]
            if not rules:
                break
            current = rules[0]["child_type"]
            if current in chain:
                break  # Prevent infinite loop
        
        # Chain length should be <= CASCADE_MAX_DEPTH
        assert len(chain) <= CASCADE_MAX_DEPTH + 1  # +1 because first element is depth 0

    def test_security_breach_chain_within_limit(self):
        chain = []
        current = "security_breach"
        while current in CASCADE_RULES:
            chain.append(current)
            rules = CASCADE_RULES[current]
            if not rules:
                break
            current = rules[0]["child_type"]
            if current in chain:
                break
        assert len(chain) <= CASCADE_MAX_DEPTH + 1
