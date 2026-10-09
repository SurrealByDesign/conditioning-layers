"""Bounded, fail-closed reader for the two accepted PNG field profiles."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import zlib

from .errors import AssetInspectionError
from .models import (
    InspectionLimits,
    InspectedChannelProfile,
    InspectedFieldProfile,
    InspectedValueKind,
)


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ANIMATION_CHUNKS = {b"acTL", b"fcTL", b"fdAT"}


@dataclass(frozen=True, slots=True)
class DecodedField:
    """Ephemeral decoded values used only while inspection is in progress."""

    profile: InspectedFieldProfile
    values: bytes


def inspect_png_bytes(
    path: Path,
    *,
    layer_id: str,
    relative_reference: str,
    limits: InspectionLimits,
) -> DecodedField:
    """Read and inspect a supported PNG without changing or retaining its pixels."""

    try:
        file_size = path.stat().st_size
    except OSError as error:
        raise AssetInspectionError(
            "asset.not_file", "Asset metadata could not be read."
        ) from error
    if file_size > limits.maximum_file_bytes:
        raise AssetInspectionError(
            "asset.resource_limit",
            "PNG exceeds the configured maximum file size.",
        )
    try:
        with path.open("rb") as stream:
            data = stream.read(limits.maximum_file_bytes + 1)
    except OSError as error:
        raise AssetInspectionError(
            "asset.not_file", "Asset bytes could not be read."
        ) from error
    return inspect_png_data(data, layer_id=layer_id,
                            relative_reference=relative_reference, limits=limits)


def inspect_png_data(
    data: bytes,
    *,
    layer_id: str,
    relative_reference: str,
    limits: InspectionLimits,
) -> DecodedField:
    """Inspect bounded in-memory PNG bytes with the same retained reader rules."""
    if len(data) > limits.maximum_file_bytes:
        raise AssetInspectionError(
            "asset.resource_limit",
            "PNG exceeds the configured maximum file size.",
        )
    checksum = hashlib.sha256(data).hexdigest()
    width, height, channels, profile, compressed = _parse_chunks(data, limits)
    values = _decode_samples(
        compressed,
        width=width,
        height=height,
        channels=channels,
        limits=limits,
    )
    if channels == 3:
        values = _collapse_identical_rgb(values)

    distinct = set(values)
    minimum = min(distinct)
    maximum = max(distinct)
    binary = distinct.issubset({0, 255})
    zero_count = values.count(0)
    full_count = values.count(255)
    measured = InspectedFieldProfile(
        layer_id=layer_id,
        relative_path=relative_reference,
        checksum=checksum,
        width=width,
        height=height,
        channel_count=channels,
        channel_profile=profile,
        minimum_normalized_value=minimum / 255,
        maximum_normalized_value=maximum / 255,
        finite_values=True,
        value_kind=(
            InspectedValueKind.BINARY
            if binary
            else InspectedValueKind.CONTINUOUS
        ),
        distinct_value_count=len(distinct),
        zero_value_count=zero_count,
        full_value_count=full_count,
        nonzero_value_count=len(values) - zero_count,
    )
    return DecodedField(profile=measured, values=values)


def _parse_chunks(
    data: bytes,
    limits: InspectionLimits,
) -> tuple[int, int, int, InspectedChannelProfile, bytes]:
    if not data.startswith(_PNG_SIGNATURE):
        raise AssetInspectionError("asset.invalid_png", "Invalid PNG signature.")

    offset = len(_PNG_SIGNATURE)
    seen_ihdr = False
    seen_idat = False
    ended_idat = False
    seen_iend = False
    seen_plte = False
    width = height = channels = color_type = 0
    channel_profile = InspectedChannelProfile.GRAYSCALE_8
    idat_parts: list[bytes] = []

    while offset < len(data):
        if len(data) - offset < 12:
            raise AssetInspectionError("asset.invalid_png", "Truncated PNG chunk.")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        if (
            any(not (65 <= value <= 90 or 97 <= value <= 122) for value in chunk_type)
            or not 65 <= chunk_type[2] <= 90
        ):
            raise AssetInspectionError("asset.invalid_png", "Invalid PNG chunk type.")
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise AssetInspectionError("asset.invalid_png", "Truncated PNG chunk data.")
        chunk_data = data[offset + 8 : offset + 8 + length]
        stored_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if stored_crc != actual_crc:
            raise AssetInspectionError("asset.invalid_png", "PNG chunk CRC mismatch.")

        if not seen_ihdr and chunk_type != b"IHDR":
            raise AssetInspectionError("asset.invalid_png", "IHDR must be first.")
        if chunk_type == b"IHDR":
            if seen_ihdr or length != 13:
                raise AssetInspectionError("asset.invalid_png", "Invalid PNG IHDR.")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)
            _validate_header(
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
                limits,
            )
            if color_type == 0:
                channels = 1
                channel_profile = InspectedChannelProfile.GRAYSCALE_8
            else:
                channels = 3
                channel_profile = InspectedChannelProfile.RGB_IDENTICAL_8
            seen_ihdr = True
        elif chunk_type in _ANIMATION_CHUNKS:
            raise AssetInspectionError(
                "asset.unsupported_mode", "Animated PNG fields are unsupported."
            )
        elif chunk_type == b"eXIf":
            raise AssetInspectionError(
                "asset.unsupported_mode",
                "PNG orientation metadata is unsupported for spatial fields.",
            )
        elif chunk_type == b"PLTE":
            if (
                color_type != 2
                or seen_plte
                or seen_idat
                or length == 0
                or length % 3 != 0
                or length > 768
            ):
                raise AssetInspectionError("asset.invalid_png", "Invalid PNG PLTE.")
            seen_plte = True
        elif chunk_type == b"IDAT":
            if ended_idat:
                raise AssetInspectionError(
                    "asset.invalid_png", "PNG IDAT chunks must be consecutive."
                )
            seen_idat = True
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0 or not seen_idat:
                raise AssetInspectionError("asset.invalid_png", "Invalid PNG IEND.")
            seen_iend = True
            offset = chunk_end
            break
        else:
            if seen_idat:
                ended_idat = True
            if chunk_type and chunk_type[0] & 0x20 == 0:
                raise AssetInspectionError(
                    "asset.invalid_png", "Unknown critical PNG chunk."
                )
        offset = chunk_end

    if not seen_iend or offset != len(data):
        raise AssetInspectionError(
            "asset.invalid_png", "PNG is missing a final IEND chunk or has trailing data."
        )
    return width, height, channels, channel_profile, b"".join(idat_parts)


def _validate_header(
    width: int,
    height: int,
    bit_depth: int,
    color_type: int,
    compression: int,
    filter_method: int,
    interlace: int,
    limits: InspectionLimits,
) -> None:
    if width <= 0 or height <= 0:
        raise AssetInspectionError("asset.invalid_png", "PNG dimensions must be positive.")
    if (
        width > limits.maximum_width
        or height > limits.maximum_height
        or width * height > limits.maximum_pixels
    ):
        raise AssetInspectionError(
            "asset.resource_limit", "PNG dimensions exceed configured inspection limits."
        )
    if bit_depth != 8 or color_type not in {0, 2}:
        raise AssetInspectionError(
            "asset.unsupported_mode",
            "Only 8-bit grayscale and 8-bit truecolor PNG fields are supported.",
        )
    if compression != 0 or filter_method != 0:
        raise AssetInspectionError("asset.invalid_png", "Unsupported PNG coding method.")
    if interlace != 0:
        raise AssetInspectionError(
            "asset.unsupported_mode", "Interlaced PNG fields are unsupported."
        )


def _decode_samples(
    compressed: bytes,
    *,
    width: int,
    height: int,
    channels: int,
    limits: InspectionLimits,
) -> bytes:
    row_size = width * channels
    expected_size = (row_size + 1) * height
    if expected_size > limits.maximum_decoded_bytes:
        raise AssetInspectionError(
            "asset.resource_limit", "Decoded PNG exceeds the configured byte limit."
        )
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected_size + 1)
        if decoder.unconsumed_tail or len(raw) > expected_size:
            raise AssetInspectionError(
                "asset.resource_limit", "PNG decompressed beyond its declared dimensions."
            )
        remaining = expected_size + 1 - len(raw)
        if remaining > 0:
            raw += decoder.flush(remaining)
    except AssetInspectionError:
        raise
    except zlib.error as error:
        raise AssetInspectionError(
            "asset.invalid_png", "PNG image data is malformed."
        ) from error
    if (
        len(raw) != expected_size
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise AssetInspectionError(
            "asset.invalid_png", "PNG image data is truncated or has excess data."
        )

    output = bytearray(row_size * height)
    previous = bytearray(row_size)
    for row_index in range(height):
        start = row_index * (row_size + 1)
        filter_type = raw[start]
        scanline = bytearray(raw[start + 1 : start + 1 + row_size])
        _unfilter(scanline, previous, channels, filter_type)
        output[row_index * row_size : (row_index + 1) * row_size] = scanline
        previous = scanline
    return bytes(output)


def _unfilter(
    row: bytearray,
    previous: bytearray,
    bytes_per_pixel: int,
    filter_type: int,
) -> None:
    if filter_type == 0:
        return
    if filter_type not in {1, 2, 3, 4}:
        raise AssetInspectionError("asset.invalid_png", "Invalid PNG row filter.")
    for index in range(len(row)):
        left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        above = previous[index]
        upper_left = (
            previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        )
        if filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = above
        elif filter_type == 3:
            predictor = (left + above) // 2
        else:
            predictor = _paeth(left, above, upper_left)
        row[index] = (row[index] + predictor) & 0xFF


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _collapse_identical_rgb(values: bytes) -> bytes:
    collapsed = bytearray(len(values) // 3)
    for pixel_index, offset in enumerate(range(0, len(values), 3)):
        red, green, blue = values[offset : offset + 3]
        if red != green or red != blue:
            raise AssetInspectionError(
                "asset.rgb_channels_differ",
                "RGB field channels differ at one or more pixels.",
            )
        collapsed[pixel_index] = red
    return bytes(collapsed)
