"""A missing live stack or skipped test must never certify CI integration."""

import os

import pytest

_skipped = []


def pytest_runtest_logreport(report):
    if report.skipped:
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    if os.getenv("REQUIRE_LIVE_STACK") == "1" and _skipped:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_sep("=", f"Live-stack validation failed: {len(_skipped)} skipped checks", red=True)
