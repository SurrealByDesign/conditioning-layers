"""Structured internal failures for read-only Influence Field inspection."""

from __future__ import annotations


class AssetInspectionError(Exception):
    """A fail-closed asset inspection failure with a stable finding code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

