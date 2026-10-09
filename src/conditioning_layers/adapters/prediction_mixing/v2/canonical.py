"""Canonical JSON and SHA-256 helpers for Translation Plan v2 only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math


MAX_SAFE_INTEGER = (1 << 53) - 1


class CanonicalizationError(ValueError):
    """A value cannot be represented by the ADR-0008 canonical contract."""


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic UTF-8 JSON with no BOM or trailing newline."""

    return _render(_portable(value)).encode("utf-8")


def canonical_json_text(value: object) -> str:
    """Return the canonical JSON text used by Translation Plan v2."""

    return canonical_json_bytes(value).decode("utf-8")


def sha256_canonical(value: object) -> str:
    """Hash canonical bytes for one immutable v2 identity boundary."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def portable_value(value: object) -> object:
    """Project supported immutable values into JSON-compatible material."""

    return _portable(value)


def _portable(value: object) -> object:
    if is_dataclass(value):
        return {
            item.name: _portable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Enum):
        return _portable(value.value)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("canonical object keys must be strings")
            _require_unicode_scalars(key)
            result[key] = _portable(item)
        return result
    if isinstance(value, tuple | list):
        return [_portable(item) for item in value]
    if isinstance(value, str):
        _require_unicode_scalars(value)
        return value
    if value is None or isinstance(value, bool | int | float):
        return value
    raise CanonicalizationError(
        f"unsupported canonical value type: {type(value)!r}"
    )


def _render(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        _require_unicode_scalars(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise CanonicalizationError(
                "canonical integers must be within the interoperable safe range"
            )
        return str(value)
    if isinstance(value, float):
        return _render_float(value)
    if isinstance(value, list):
        return "[" + ",".join(_render(item) for item in value) + "]"
    if isinstance(value, dict):
        ordered = sorted(value, key=_utf16_sort_key)
        return "{" + ",".join(
            _render(key) + ":" + _render(value[key]) for key in ordered
        ) + "}"
    raise CanonicalizationError(
        f"unsupported canonical portable type: {type(value)!r}"
    )


def _render_float(value: float) -> str:
    if not math.isfinite(value):
        raise CanonicalizationError("canonical floating-point values must be finite")
    if value == 0.0:
        return "0"

    text = repr(value).lower()
    magnitude = abs(value)
    if 1e-6 <= magnitude < 1e21:
        fixed = format(Decimal(text), "f")
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        return fixed

    if "e" not in text:
        text = format(value, ".17e")
    mantissa, exponent_text = text.split("e", 1)
    if mantissa.endswith(".0"):
        mantissa = mantissa[:-2]
    exponent = int(exponent_text)
    sign = "+" if exponent >= 0 else ""
    return f"{mantissa}e{sign}{exponent}"


def _utf16_sort_key(value: str) -> bytes:
    _require_unicode_scalars(value)
    return value.encode("utf-16-be")


def _require_unicode_scalars(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CanonicalizationError(
            "canonical strings must not contain lone surrogate code points"
        )
