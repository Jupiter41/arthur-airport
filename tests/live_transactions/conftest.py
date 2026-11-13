"""The dedicated CI job forbids skipped validation checks."""
from tests.integration.live_required import pytest_runtest_logreport, pytest_sessionfinish  # noqa: F401
