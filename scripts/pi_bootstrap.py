"""Create production secrets on the Pi without printing credentials."""
import json
import os
from pathlib import Path
import secrets

root = Path("/opt/arthur-airport")
os.umask(0o077)
env = root / ".env.pi"
if not env.exists():
    password = secrets.token_urlsafe(32)
    clients = json.dumps({"arthur": {"secret": password, "role": "approver"}}, separators=(",", ":"))
    env.write_text("AIRPORT_DOMAIN=airportdt.duckdns.org\n"
                   f"NEO4J_PASSWORD={secrets.token_urlsafe(32)}\n"
                   f"JWT_SECRET={secrets.token_urlsafe(48)}\n"
                   f"AUTH_CLIENTS={clients}\n")
    (root / "operator-credentials.txt").write_text(f"Operator ID: arthur\nPassword: {password}\n")
env.chmod(0o600)
print("Production secrets present with mode 0600")
