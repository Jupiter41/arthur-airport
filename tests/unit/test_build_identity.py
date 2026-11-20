"""RC14 identity detects overlays and changes in actual executable/config files."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("identity_under_test", ROOT / "services/_common/build_identity.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def test_identity_detects_shared_service_and_config_changes(tmp_path):
    for path, content in {"main.py": "x=1", "_common/contract.py": "v=1", "config/airport.yaml": "lanes: 8"}.items():
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    expected = identity.write_identity(tmp_path, "flight-service", "a" * 40, False)
    assert identity.inspect_identity(tmp_path)["integrity"]
    for path, key in (("main.py", "artifact_sha256"), ("_common/contract.py", "shared_sha256"),
                      ("config/airport.yaml", "config_sha256")):
        file = tmp_path / path
        content = file.read_text()
        file.write_text(content + "\n# stale overlay")
        report = identity.inspect_identity(tmp_path)
        assert not report["integrity"] and f"{key} mismatch" in report["errors"]
        file.write_text(content)
        assert identity.inspect_identity(tmp_path)["integrity"]
    (tmp_path / "unexpected.py").write_text("x=2")
    assert not identity.inspect_identity(tmp_path)["integrity"]
    assert expected["source_sha256"] == expected["artifact_sha256"]


def test_unknown_identity_cannot_certify_required_image(tmp_path, monkeypatch):
    monkeypatch.setenv("ART_BUILD_ROOT", str(tmp_path))
    monkeypatch.setenv("ART_REQUIRE_BUILD_IDENTITY", "1")
    assert not identity.identity_ready()
    identity.write_identity(tmp_path, "flight-service", "unversioned", False)
    assert not identity.identity_ready()
