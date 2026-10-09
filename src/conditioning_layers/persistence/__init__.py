"""Prototype-only JSON persistence for Conditioning Documents."""

from .errors import (
    AssetPathError,
    DocumentEncodeError,
    DocumentIOError,
    LoadResult,
    PersistenceError,
    PersistenceFinding,
)
from .json_codec import (
    PROTOTYPE_FORMAT_ID,
    decode_document,
    encode_document,
    load_document,
    save_document,
)
from .migrations import (
    COMPOSITION_POLICY_FORMAT_VERSION,
    CURRENT_FORMAT_VERSION,
    PrototypeFormatVersion,
)
from .paths import (
    document_asset_root,
    normalize_asset_reference,
    resolve_asset_path,
)

__all__ = [
    "COMPOSITION_POLICY_FORMAT_VERSION",
    "CURRENT_FORMAT_VERSION",
    "PROTOTYPE_FORMAT_ID",
    "AssetPathError",
    "DocumentEncodeError",
    "DocumentIOError",
    "LoadResult",
    "PersistenceError",
    "PersistenceFinding",
    "PrototypeFormatVersion",
    "decode_document",
    "document_asset_root",
    "encode_document",
    "load_document",
    "normalize_asset_reference",
    "resolve_asset_path",
    "save_document",
]
