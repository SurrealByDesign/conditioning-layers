"""Exact-integer canonical JSON for the direct post-v1 host artifacts."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import json
from types import MappingProxyType


def freeze_json(value: object) -> object:
    """Freeze new graph values without repairing malformed object keys."""
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("Graph object keys must be strings")
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


def canonical_bytes(value: object) -> bytes:
    return json.dumps(json_value(value), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
