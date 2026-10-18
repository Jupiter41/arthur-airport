"""Shared synthetic rates, validation, content identity and carrier overrides."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import re


def load_default_rates() -> dict:
    return json.loads((Path(__file__).parent / "data" / "cost_rates.json").read_text(encoding="utf-8"))


def rates_version(rates: dict) -> str:
    encoded = json.dumps(rates, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def merge_rates(base: dict, overrides: dict) -> dict:
    """Validate a patch without mutating the committed table, including on failure."""
    result = deepcopy(base)

    def merge(target: dict, patch: dict, schema: dict, path: str = "") -> None:
        for key, value in patch.items():
            here = f"{path}.{key}" if path else key
            if key not in schema:
                raise ValueError(f"unknown rate field: {here}")
            expected = schema[key]
            if key.startswith("_"):
                raise ValueError(f"read-only rate metadata: {here}")
            if here == "airline_overrides":
                if not isinstance(value, dict):
                    raise ValueError("airline_overrides must be an object")
                for code, carrier_patch in value.items():
                    if not re.fullmatch(r"[A-Z]{2,3}", code) or not isinstance(carrier_patch, dict):
                        raise ValueError("invalid synthetic airline override")
                    if "airline_overrides" in carrier_patch:
                        raise ValueError("nested airline_overrides are invalid")
                    carrier = target[key].setdefault(code, {})
                    merge(carrier, carrier_patch, base, f"airline_overrides.{code}")
            elif isinstance(expected, dict):
                if not isinstance(value, dict):
                    raise ValueError(f"{here} must be an object")
                merge(target.setdefault(key, {}), value, expected, here)
            elif isinstance(expected, list):
                if not isinstance(value, list):
                    raise ValueError(f"{here} must be a list")
                if here.endswith("eu261"):
                    if len(value) != len(expected):
                        raise ValueError(f"{here} must contain {len(expected)} entries")
                    rows = []
                    for index, (row, template) in enumerate(zip(value, expected)):
                        if not isinstance(row, dict) or set(row) != set(template):
                            raise ValueError(f"invalid tier at {here}.{index}")
                        if template.get("assistance_only") and row.get("assistance_only") is not True:
                            raise ValueError("assistance-only tiers cannot become compensation tiers without an amount")
                        checked = deepcopy(template)
                        merge(checked, row, template, f"{here}.{index}")
                        rows.append(checked)
                    target[key] = rows
                elif all(type(item) is int and 0 <= item <= 23 for item in value):
                    target[key] = list(value)
                else:
                    raise ValueError(f"invalid hour list: {here}")
            elif isinstance(expected, bool):
                if type(value) is not bool:
                    raise ValueError(f"{here} must be boolean")
                target[key] = value
            elif isinstance(expected, (int, float)):
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{here} must be a finite non-negative number")
                target[key] = value
            elif type(value) is not type(expected):
                raise ValueError(f"type mismatch for {here}")
            else:
                target[key] = value

    merge(result, overrides, load_default_rates())
    return result


def resolve_rates_for_airline(rates: dict, airline_code: str | None) -> dict:
    patch = rates.get("airline_overrides", {}).get(airline_code or "")
    if not patch:
        return rates
    result = deepcopy(rates)

    def merge(target: dict, update: dict) -> None:
        for key, value in update.items():
            if isinstance(value, dict):
                merge(target.setdefault(key, {}), value)
            else:
                target[key] = deepcopy(value)

    merge(result, patch)
    return result
