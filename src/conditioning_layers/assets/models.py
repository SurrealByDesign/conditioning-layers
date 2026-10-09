"""Immutable neutral results for Influence Field asset inspection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from conditioning_layers.domain import PromptLayer, ValidationFinding


INSPECTION_TOOL_VERSION = "conditioning-layers.png-field-inspector.v1"
FIELD_RELATIONSHIP_CERTIFICATE_FORMAT = (
    "conditioning-layers.field-relationship-certificate.v1"
)
FIELD_RELATIONSHIP_CERTIFICATE_VERSION = 1
ORDERED_N_WAY_RELATIONSHIP_POLICY_IDENTIFIER = (
    "prediction-mixing.ordered-n-way-no-overlap.v1"
)
ORDERED_N_WAY_RELATIONSHIP_POLICY_VERSION = 1


class InspectedChannelProfile(str, Enum):
    """PNG channel arrangements accepted without conversion."""

    GRAYSCALE_8 = "grayscale_8"
    RGB_IDENTICAL_8 = "rgb_identical_8"


class InspectedValueKind(str, Enum):
    """Classification of original 8-bit sample values."""

    BINARY = "binary"
    CONTINUOUS = "continuous"


class CertifiedOverlap(str, Enum):
    """Pairwise state produced only from two compatible inspected fields."""

    NO_OVERLAP = "no_overlap"
    OVERLAP_PRESENT = "overlap_present"


class FieldRelationshipCertificationStatus(str, Enum):
    """Whether exact ordered-set measurements were certified."""

    CERTIFIED = "certified"
    UNCERTIFIED = "uncertified"


class PartitionClassification(str, Enum):
    """Relationship classification without implied execution support."""

    EXACT_DISJOINT_COMPLETE_PARTITION = "exact_disjoint_complete_partition"
    DISJOINT_WITH_GAPS = "disjoint_with_gaps"
    OVERLAPPING = "overlapping"
    MIXED_NON_PARTITION = "mixed_non_partition"
    UNABLE_TO_CERTIFY = "unable_to_certify"


@dataclass(frozen=True, slots=True)
class FieldPolarity:
    """Frozen stored-sample interpretation before requested Strength."""

    no_influence_sample: int = 0
    full_influence_sample: int = 255
    inverted: bool = False
    applied_before_strength: bool = True


@dataclass(frozen=True, slots=True)
class FieldOrientation:
    """Frozen spatial interpretation; inspection performs no transformation."""

    origin: str = "top_left"
    positive_x: str = "right"
    positive_y: str = "down"
    rotation_degrees: int = 0
    mirrored_x: bool = False
    mirrored_y: bool = False
    resizing: str = "none"
    interpolation: str = "none"
    transformation: str = "none"


@dataclass(frozen=True, slots=True)
class FieldRelationshipPolicy:
    """Narrow Prediction Mixing policy used to measure an ordered field set."""

    identifier: str = ORDERED_N_WAY_RELATIONSHIP_POLICY_IDENTIFIER
    version: int = ORDERED_N_WAY_RELATIONSHIP_POLICY_VERSION
    positive_sample_threshold: int = 0
    normalized_sum_threshold_sample: int = 255
    partition_sum_sample: int = 255
    polarity: FieldPolarity = FieldPolarity()
    orientation: FieldOrientation = FieldOrientation()


DEFAULT_FIELD_RELATIONSHIP_POLICY = FieldRelationshipPolicy()


@dataclass(frozen=True, slots=True)
class FieldRelationshipInput:
    """One ordered document-bound Prompt Layer supplied for inspection."""

    layer: PromptLayer
    document_index: int | None = None


@dataclass(frozen=True, slots=True)
class OrderedFieldRecord:
    """Portable ordered identity and measured metadata for one source field."""

    ordinal: int
    layer_id: str | None
    document_index: int | None
    portable_reference: str
    source_sha256: str | None
    width: int | None
    height: int | None
    bit_depth: int | None
    channel_profile: InspectedChannelProfile | None
    value_kind: InspectedValueKind | None
    minimum_normalized_value: float | None
    maximum_normalized_value: float | None
    inspection_certified: bool
    finding_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SharedRasterEvidence:
    """Exact raster contract shared by the ordered field set."""

    width: int | None
    height: int | None
    pixel_count: int | None
    bit_depth: int | None
    channel_interpretation: str
    normalization_rule: str
    positive_sample_threshold_normalized: float
    all_fields_satisfy: bool


@dataclass(frozen=True, slots=True)
class PairwiseRelationshipEvidence:
    """Deterministic i < j relationship evidence inside the whole certificate."""

    first_ordinal: int
    second_ordinal: int
    first_layer_id: str | None
    second_layer_id: str | None
    certified: bool
    simultaneous_positive_pixel_count: int | None
    overlap_fraction: float | None
    minimum_normalized_pairwise_sum: float | None
    maximum_normalized_pairwise_sum: float | None
    exact_complements: bool | None
    finding_codes: tuple[str, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class WholeSetRelationshipEvidence:
    """Measurements that cannot be represented by pairwise overlap alone."""

    certified: bool
    complete_coverage: bool | None
    gap_pixel_count: int | None
    gap_fraction: float | None
    maximum_simultaneous_active_field_count: int | None
    simultaneous_active_count_histogram: tuple[int, ...]
    normalized_sum_policy_threshold: float
    sum_exceeds_policy_pixel_count: int | None
    minimum_normalized_total_sum: float | None
    maximum_normalized_total_sum: float | None
    partition_sum_normalized_value: float
    partition_sum_pixel_count: int | None
    duplicate_hash_ordinal_groups: tuple[tuple[int, ...], ...]
    duplicate_reference_ordinal_groups: tuple[tuple[int, ...], ...]
    mutual_exclusion: bool | None


@dataclass(frozen=True, slots=True)
class FieldRelationshipCertificate:
    """Portable immutable evidence for one exact ordered field set."""

    format_identifier: str
    format_version: int
    relationship_policy_identifier: str
    relationship_policy_version: int
    fingerprint: str
    status: FieldRelationshipCertificationStatus
    finding_codes: tuple[str, ...]
    ordered_fields: tuple[OrderedFieldRecord, ...]
    shared_raster: SharedRasterEvidence
    pairwise_evidence: tuple[PairwiseRelationshipEvidence, ...]
    whole_set_evidence: WholeSetRelationshipEvidence
    partition_classification: PartitionClassification
    polarity: FieldPolarity
    orientation: FieldOrientation


@dataclass(frozen=True, slots=True)
class FieldRelationshipInspectionResult:
    """Field outcomes plus their whole-set certificate and full findings."""

    certificate: FieldRelationshipCertificate
    fields: tuple[FieldInspectionResult, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]


@dataclass(frozen=True, slots=True)
class InspectionLimits:
    """Conservative allocation limits for the narrow PNG reader."""

    maximum_file_bytes: int = 16 * 1024 * 1024
    maximum_width: int = 4096
    maximum_height: int = 4096
    maximum_pixels: int = 16 * 1024 * 1024
    maximum_decoded_bytes: int = 64 * 1024 * 1024


DEFAULT_INSPECTION_LIMITS = InspectionLimits()


@dataclass(frozen=True, slots=True)
class InspectedFieldProfile:
    """Measurements retained after original pixels have been discarded."""

    layer_id: str
    relative_path: str
    checksum: str
    width: int
    height: int
    channel_count: int
    channel_profile: InspectedChannelProfile
    minimum_normalized_value: float
    maximum_normalized_value: float
    finite_values: bool
    value_kind: InspectedValueKind
    distinct_value_count: int
    zero_value_count: int
    full_value_count: int
    nonzero_value_count: int
    inspection_tool_version: str = INSPECTION_TOOL_VERSION


@dataclass(frozen=True, slots=True)
class DimensionValidationResult:
    """Exact comparison against explicit execution-profile field dimensions."""

    certified: bool
    matches: bool
    expected_width: int
    expected_height: int
    observed_width: int
    observed_height: int
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    source_reference: str
    checksum: str


@dataclass(frozen=True, slots=True)
class FieldInspectionResult:
    """Read-only inspection outcome for one document-owned field asset."""

    successful: bool
    certified: bool
    profile: InspectedFieldProfile | None
    dimension_validation: DimensionValidationResult | None
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    source_reference: str
    checksum: str | None


@dataclass(frozen=True, slots=True)
class OverlapEvidence:
    """Exact pairwise measurements with no claimed execution semantics."""

    assessment: CertifiedOverlap
    total_pixel_count: int
    overlap_pixel_count: int
    overlap_fraction: float
    minimum_pairwise_sum: float
    maximum_pairwise_sum: float
    exact_complements: bool
    has_unassigned_pixels: bool
    sums_exceed_one: bool
    input_digest: str


@dataclass(frozen=True, slots=True)
class OverlapInspectionResult:
    """Certified assessment or structured failure for exactly two fields."""

    certified: bool
    evidence: OverlapEvidence | None
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    source_references: tuple[str, str]
    checksums: tuple[str | None, str | None]
    input_digest: str | None


@dataclass(frozen=True, slots=True)
class PairInspectionResult:
    """The two field outcomes and their separately certified relationship."""

    fields: tuple[FieldInspectionResult, FieldInspectionResult]
    overlap: OverlapInspectionResult
