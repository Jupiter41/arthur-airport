"""The integration gate must reject unavailable coverage, not report green."""

import os
from pathlib import Path
import subprocess
import sys


def test_required_integration_skips_fail_the_process(tmp_path):
    test_file = tmp_path / "test_unavailable.py"
    test_file.write_text("import pytest\ndef test_live():\n    pytest.skip('service absent')\n")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q", "-p", "tests.integration.live_required"],
        cwd=root, env={**os.environ, "REQUIRE_LIVE_STACK": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Live-stack validation failed: 1 skipped checks" in result.stdout
