"""Query PyPI for installed versions after explicit package-inventory consent.

Unknown packages and failed requests remain explicit; no credentials or source
are sent. This audits Python distributions, not base-image operating systems.
"""
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

root = Path("/opt/arthur-airport")
requirements = sorted({line.strip() for path in (root / "audit-input").glob("requirements-*.txt")
                       for line in path.read_text().splitlines() if line.strip()})
if not requirements:
    raise SystemExit("No installed package inventory found")
results = []
for requirement in requirements:
    name, version = requirement.split("==", 1)
    item = {"name": name, "version": version}
    try:
        request = Request(f"https://pypi.org/pypi/{quote(name)}/{quote(version)}/json",
                          headers={"User-Agent": "airport-approved-dependency-audit/1"})
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
        item["vulnerabilities"] = data.get("vulnerabilities", [])
    except Exception as exc:
        item["error"] = str(exc)
    results.append(item)
folder = root / "audit-results"
folder.mkdir(exist_ok=True)
(folder / "python-pypi.json").write_text(json.dumps(results, indent=2))
failures = [item for item in results if "error" in item]
findings = [item for item in results if item.get("vulnerabilities")]
print(json.dumps({"package_versions": len(results), "findings": findings,
                  "incomplete": failures}, indent=2))
raise SystemExit(2 if failures else 1 if findings else 0)
