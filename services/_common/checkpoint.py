"""Versioned JSON runtime checkpoints with an explicit local type whitelist."""
import json
from collections import deque
from datetime import datetime
from enum import Enum
from typing import Any, Sequence


def _encode(value: Any, types: dict[str, type]) -> Any:
    if isinstance(value, Enum):
        return {"type": type(value).__name__, "value": value.value}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, (set, tuple, deque)):
        return {"type": type(value).__name__, "value": [_encode(v, types) for v in value]}
    if isinstance(value, dict):
        return {"type": "dict", "value": [[_encode(k, types), _encode(v, types)] for k, v in value.items()]}
    if isinstance(value, list):
        return [_encode(v, types) for v in value]
    if type(value) in types.values():
        return {"type": type(value).__name__, "value": _encode(vars(value), types)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported checkpoint value: {type(value).__name__}")


def _decode(value: Any, types: dict[str, type]) -> Any:
    if isinstance(value, list):
        return [_decode(v, types) for v in value]
    if not isinstance(value, dict):
        return value
    kind, data = value["type"], value["value"]
    if kind == "datetime":
        return datetime.fromisoformat(data)
    if kind == "dict":
        return {_decode(k, types): _decode(v, types) for k, v in data}
    if kind in ("set", "tuple", "deque"):
        return {"set": set, "tuple": tuple, "deque": deque}[kind](_decode(v, types) for v in data)
    cls = types[kind]
    if issubclass(cls, Enum):
        return cls(data)
    obj = cls.__new__(cls)
    obj.__dict__.update(_decode(data, types))
    return obj


class SnapshotCodec:
    def __init__(self, types: Sequence[type], fields: Sequence[str], publish_fields: Sequence[str] = ()) -> None:
        self.types = {t.__name__: t for t in types}
        self.fields = fields
        self.publish_fields = publish_fields

    def dump(self, state: Any) -> str:
        values = {k: getattr(state, k) for k in self.fields}
        return json.dumps({"version": 1, "state": _encode(values, self.types)})

    def restore(self, state: Any, document: str) -> None:
        saved = json.loads(document)
        if saved["version"] != 1:
            raise ValueError("Unsupported checkpoint version")
        for key, value in _decode(saved["state"], self.types).items():
            if key not in self.fields:
                raise ValueError(f"Unknown checkpoint field: {key}")
            setattr(state, key, value)
