"""Exceptions for programmer misuse of document operations.

User-authored invalid document content is reported by structured validation
findings. These exceptions cover invalid operation requests, such as editing a
layer that is not present or inserting a duplicate identity.
"""


class DomainOperationError(ValueError):
    """Base exception for invalid domain operation requests."""


class LayerNotFoundError(DomainOperationError):
    """Raised when an operation targets a layer identity not in the document."""


class DuplicateLayerIdError(DomainOperationError):
    """Raised when an operation would introduce a duplicate layer identity."""


class InvalidLayerPositionError(DomainOperationError):
    """Raised when an add or move position is outside the valid collection range."""
