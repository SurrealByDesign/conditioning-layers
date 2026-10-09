"""ADR-0026 exact sample-code normalization; no tensors or host dependency."""

import math
import struct


def _rounded_quotient(numerator: int, denominator: int) -> int:
    quotient, remainder = divmod(numerator, denominator)
    twice = remainder << 1
    return quotient + (twice > denominator or (twice == denominator and quotient & 1))


def round_ratio_to_binary32_bits(numerator: int, denominator: int) -> int:
    """Round an exact nonnegative unit ratio directly to IEEE binary32 bits.

    No binary64 division precedes rounding. Subnormals use the 2**-149 grid;
    normal values use the grid selected by the exact integer exponent.
    No floating conversion is used, including for a subnormal output.
    """
    if (type(numerator) is not int or type(denominator) is not int
            or denominator <= 0 or not 0 <= numerator <= denominator):
        raise ValueError("A bounded nonnegative exact unit ratio is required")
    if numerator == 0:
        return 0
    exponent = numerator.bit_length() - denominator.bit_length()
    if exponent >= 0:
        if numerator < denominator << exponent:
            exponent -= 1
    elif numerator << -exponent < denominator:
        exponent -= 1
    if exponent < -126:
        bits = _rounded_quotient(numerator << 149, denominator)
    else:
        significand = _rounded_quotient(numerator << (23 - exponent), denominator)
        if significand == 1 << 24:
            significand >>= 1
            exponent += 1
        bits = ((exponent + 127) << 23) | (significand - (1 << 23))
    return bits


def round_ratio_to_binary32(numerator: int, denominator: int) -> float:
    """Expose the already-rounded value as a Python float for scalar callers."""
    return struct.unpack(">f", struct.pack(">I", round_ratio_to_binary32_bits(numerator, denominator)))[0]


def _strength_ratio(strength: float) -> tuple[int, int]:
    if type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("Strength must be finite binary64 in [0,1]")
    return float(strength).as_integer_ratio()


def normalize_sample_codes_bits(codes: tuple[int, ...], strengths: tuple[float, ...]) -> tuple[int, ...]:
    """Prepare ordered exact ratios with support decided before any product.

    The registered caller restricts the collection to exactly three entries.
    Binary64 denominators are powers of two, at most 2**1074. Aligning them
    yields bounded integers; the common authored field denominator 255 cancels.
    """
    if not codes or len(codes) != len(strengths):
        raise ValueError("Ordered samples and Strengths must have the same nonzero length")
    if any(type(code) is not int or not 0 <= code <= 255 for code in codes):
        raise ValueError("Authored field codes must be uint8 integers")
    ratios = tuple(_strength_ratio(strength) for strength in strengths)
    support = tuple(code > 0 and strength > 0 for code, strength in zip(codes, strengths))
    if not any(support):
        return (0,) * len(codes)
    common_denominator = max(denominator for _, denominator in ratios)
    products = tuple(
        code * numerator * (common_denominator // denominator) if positive else 0
        for code, (numerator, denominator), positive in zip(codes, ratios, support)
    )
    total = sum(products)
    return tuple(round_ratio_to_binary32_bits(product, total) for product in products)


def normalize_sample_codes(codes: tuple[int, ...], strengths: tuple[float, ...]) -> tuple[float, ...]:
    """Scalar view of normalized binary32 outputs; node installs integer bits."""
    return tuple(struct.unpack(">f", struct.pack(">I", bits))[0]
                 for bits in normalize_sample_codes_bits(codes, strengths))


def _sample_codebook() -> dict[float, int]:
    # Pinned LoadImageMask: RGB24/Pillow use n/255; PyAV gray -> gbrpf32le
    # uses n*256/65535. Both exact binary32 codebooks are injective together.
    book: dict[float, int] = {}
    for code in range(256):
        for value in (round_ratio_to_binary32(code, 255),
                      round_ratio_to_binary32(code * 256, 65535)):
            if value in book and book[value] != code:
                raise RuntimeError("Ambiguous authored sample-code correspondence")
            book[value] = code
    return book


_SAMPLE_CODEBOOK = _sample_codebook()


def recover_sample_code(value: float) -> int:
    """Recover only a bit-exact accepted decoded value, never snap or clamp."""
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("A finite decoded binary32 field sample is required")
    try:
        return _SAMPLE_CODEBOOK[value]
    except KeyError as error:
        raise ValueError("Field sample is outside the governed decoder codebooks") from error
