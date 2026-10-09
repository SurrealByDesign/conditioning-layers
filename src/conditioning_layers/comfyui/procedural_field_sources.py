"""Pure procedural field codes; MASK encoding is a runtime boundary."""

import hashlib
import math

from conditioning_layers.comfyui.influence_field_sources import codes_to_mask


P = 32768
E = 2**64
PROCEDURAL_FIELD_NODE_CLASS_NAMES = (
    "ConditioningLayersScatterField",
    "ConditioningLayersCyclicPartitionField",
    "ConditioningLayersVoronoiPartitionField",
    "ConditioningLayersNoiseField",
    "ConditioningLayersPolarPartitionField",
)


def _integer(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")


def _kept_sites(seed, grid, density_percent):
    """Rank by keep word, row, column; other words never break keep ties."""
    sites = []
    for j in range(grid):
        for i in range(grid):
            digest = hashlib.sha256(
                f"conditioning-layers.scatter-field.v1:{seed}:{i}:{j}".encode("ascii")
            ).digest()
            words = tuple(int.from_bytes(digest[k:k + 8], "big") for k in range(0, 32, 8))
            sites.append((words[0], j, i, *words[1:]))
    sites.sort(key=lambda site: site[:3])
    return tuple(sites[:(grid * grid * density_percent + 50) // 100])


def scatter_field_codes(seed, grid, density_percent, jitter_percent, radius,
                        radius_variation_percent, shape):
    """Return 16384 row-major integer codes, using exact per-feature row spans.

    Geometry uses 256 units per cell and inclusive boundaries. Unwrapped spans
    are mapped modulo 128 to the torus; radius <= 32 means each span is shorter
    than a period, so no sample is lost or ambiguously assigned at a seam.
    """
    for name, value, low, high in (
        ("seed", seed, 0, 4294967295), ("grid", grid, 1, 32),
        ("density_percent", density_percent, 0, 100),
        ("jitter_percent", jitter_percent, 0, 100),
        ("radius_variation_percent", radius_variation_percent, 0, 100),
    ):
        _integer(name, value, low, high)
    if (type(radius) not in (int, float) or not 0.5 <= radius <= 32
            or not math.isfinite(radius) or 2 * radius != int(2 * radius)):
        raise ValueError("radius must be finite in [0.5, 32.0] in half-cell steps")
    if shape not in ("disk", "square", "diamond"):
        raise ValueError("shape must be disk, square or diamond")

    codes = [0] * 16384
    r0 = 128 * int(2 * radius)
    denominator = 2 * grid * 100 * E
    for _, j, i, wx, wy, wr in _kept_sites(seed, grid, density_percent):
        cx = P * ((2 * i + 1) * 100 * E + jitter_percent * (2 * wx + 1 - E)) // denominator
        cy = P * ((2 * j + 1) * 100 * E + jitter_percent * (2 * wy + 1 - E)) // denominator
        r = r0 - (r0 * radius_variation_percent * wr) // (100 * E)
        # ceil((cy-r-128)/256) through floor((cy+r-128)/256).
        first_y = -(-(cy - r - 128) // 256)
        last_y = (cy + r - 128) // 256
        for y in range(first_y, last_y + 1):
            dy = abs(256 * y + 128 - cy)
            if shape == "disk":
                extent = math.isqrt(r * r - dy * dy)
            elif shape == "diamond":
                extent = r - dy
            else:
                extent = r
            first_x = -(-(cx - extent - 128) // 256)
            last_x = (cx + extent - 128) // 256
            length = last_x - first_x + 1
            start = first_x % 128
            row = (y % 128) * 128
            before_seam = min(length, 128 - start)
            codes[row + start:row + start + before_seam] = [255] * before_seam
            if length > before_seam:
                codes[row:row + length - before_seam] = [255] * (length - before_seam)
    return tuple(codes)


class ConditioningLayersScatterField:
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "generate"
    CATEGORY = "conditioning/conditioning_layers/fields"
    DESCRIPTION = (
        "Deterministic seeded scatter on a stratified lattice of grid x grid sites. "
        "Keeps exactly (grid*grid*density_percent + 50)//100 features, with seeded "
        "jitter and radius variation. Wraparound geometry is seamless; the output "
        "is the binary union of all kept features. Pair with Invert for complementary "
        "FIXED fields; use Blur for soft/BLENDED variants."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 4294967295, "step": 1,
                             "control_after_generate": False,
                             "tooltip": "Fixed seed for versioned SHA-256 site selection, jitter and radii."}),
            "grid": ("INT", {"default": 8, "min": 1, "max": 32,
                             "tooltip": "Stratified lattice: grid x grid candidate sites over 128 cells."}),
            "density_percent": ("INT", {"default": 50, "min": 0, "max": 100,
                                        "tooltip": "Exact kept feature count: (grid*grid*density + 50)//100; not area coverage."}),
            "jitter_percent": ("INT", {"default": 75, "min": 0, "max": 100,
                                       "tooltip": "Seeded center displacement, up to half a lattice cell per axis at 100%."}),
            "radius": ("FLOAT", {"default": 5.0, "min": 0.5, "max": 32.0, "step": 0.5,
                                 "tooltip": "Maximum feature radius in field cells. Inclusive, seamless wraparound geometry."}),
            "radius_variation_percent": ("INT", {"default": 25, "min": 0, "max": 100,
                                                 "tooltip": "Seeded reduction from the maximum radius; zero keeps equal radii."}),
            "shape": (["disk", "square", "diamond"], {"default": "disk",
                       "tooltip": "Binary union of inclusive disk, axis-aligned square or diamond features."}),
        }}

    def generate(self, seed, grid, density_percent, jitter_percent, radius,
                 radius_variation_percent, shape):
        codes = scatter_field_codes(seed, grid, density_percent, jitter_percent,
                                    radius, radius_variation_percent, shape)
        return (codes_to_mask(codes),)


def cyclic_partition_field_codes(columns, rows, members, shift):
    """Four row-major binary fields; sample-center ownership, no interpolation.

    Active members partition the canvas exactly, but some may have no support.
    Unused members are zero. Geometry uses only Python integer arithmetic.
    """
    for name, value, low, high in (
        ("columns", columns, 1, 32), ("rows", rows, 1, 32),
        ("members", members, 2, 4), ("shift", shift, 0, 3),
    ):
        _integer(name, value, low, high)
    fields = [[0] * 16384 for _ in range(4)]
    for y in range(128):
        j = ((2 * y + 1) * rows) // 256
        for x in range(128):
            i = ((2 * x + 1) * columns) // 256
            owner = (i + shift * j) % members
            fields[owner][y * 128 + x] = 255
    return tuple(tuple(codes) for codes in fields)


class ConditioningLayersCyclicPartitionField:
    RETURN_TYPES = ("MASK", "MASK", "MASK", "MASK")
    RETURN_NAMES = ("field_a", "field_b", "field_c", "field_d")
    FUNCTION = "generate"
    CATEGORY = "conditioning/conditioning_layers/fields"
    DESCRIPTION = (
        "Exact binary cyclic partition: each sample belongs to one of the first "
        "members outputs; unused outputs are zero. Nonempty members form disjoint "
        "FIXED assignments with full coverage and no thresholding. Omit or disable "
        "empty Layer branches. Field Blur makes soft variants for BLENDED use; "
        "blurred members can overlap and are no longer safe as FIXED partitions."
    )

    @classmethod
    def INPUT_TYPES(cls):
        # Native number widgets allow dragging/stepping and typed exact entry.
        return {"required": {
            "columns": ("INT", {"default": 8, "min": 1, "max": 32, "step": 1,
                                "display": "number",
                                "tooltip": "Number of sample-center cells across the 128-sample canvas."}),
            "rows": ("INT", {"default": 8, "min": 1, "max": 32, "step": 1,
                             "display": "number",
                             "tooltip": "Number of sample-center cells down the 128-sample canvas."}),
            "members": ("INT", {"default": 2, "min": 2, "max": 4, "step": 1,
                                "display": "number",
                                "tooltip": "Use the first 2, 3 or 4 outputs. Empty branches must be omitted or disabled."}),
            "shift": ("INT", {"default": 1, "min": 0, "max": 3, "step": 1,
                              "display": "number",
                              "tooltip": "Owner = (column + shift*row) % members. Zero gives vertical bands."}),
        }}

    def generate(self, columns, rows, members, shift):
        return tuple(codes_to_mask(codes) for codes in
                     cyclic_partition_field_codes(columns, rows, members, shift))


def _voronoi_sites(seed, grid, jitter_percent, members, assignment_mode, member_shift):
    """Row-major (cx, cy, w_tie, j, i, owner), all in integer fixed point."""
    sites = []
    denominator = 2 * grid * 100 * E
    for j in range(grid):
        for i in range(grid):
            digest = hashlib.sha256(
                f"conditioning-layers.voronoi-partition.v1:{seed}:{i}:{j}".encode("ascii")
            ).digest()
            wx, wy, wm, wt = (int.from_bytes(digest[k:k + 8], "big")
                              for k in range(0, 32, 8))
            # Retained Scatter jitter: floor once, after center + displacement.
            cx = P * ((2 * i + 1) * 100 * E + jitter_percent * (2 * wx + 1 - E)) // denominator
            cy = P * ((2 * j + 1) * 100 * E + jitter_percent * (2 * wy + 1 - E)) // denominator
            owner = j * grid + i if assignment_mode == "cyclic" else (wm * members) >> 64
            sites.append((cx, cy, wt, j, i, (owner + member_shift) % members))
    return tuple(sites)


def _voronoi_partition_codes(sites):
    """Exact bounded search; minimize (distance2, w_tie, j, i) explicitly.

    Precompute 128 squared distances per axis/site. No spatial index, tensor
    runtime, float placement, square root, or dependence on traversal order.
    """
    best_distance = [2 * P * P] * 16384
    best_tie = [None] * 16384
    owners = [0] * 16384
    for cx, cy, wt, j, i, owner in sites:
        tie = (wt, j, i)
        xs = [((256 * x + 128 - cx + P // 2) % P - P // 2) ** 2 for x in range(128)]
        ys = [((256 * y + 128 - cy + P // 2) % P - P // 2) ** 2 for y in range(128)]
        for y, dy2 in enumerate(ys):
            row = y * 128
            for x, dx2 in enumerate(xs):
                index = row + x
                distance = dx2 + dy2
                if (distance < best_distance[index]
                        or (distance == best_distance[index] and tie < best_tie[index])):
                    best_distance[index] = distance
                    best_tie[index] = tie
                    owners[index] = owner
    fields = [[0] * 16384 for _ in range(4)]
    for index, owner in enumerate(owners):
        fields[owner][index] = 255
    return tuple(tuple(codes) for codes in fields)


def voronoi_partition_field_codes(seed, grid, jitter_percent, members,
                                  assignment_mode, member_shift):
    """Four binary code planes; exactly one active owner at every sample."""
    for name, value, low, high in (
        ("seed", seed, 0, 4294967295), ("grid", grid, 1, 16),
        ("jitter_percent", jitter_percent, 0, 100), ("members", members, 2, 4),
        ("member_shift", member_shift, 0, 3),
    ):
        _integer(name, value, low, high)
    if assignment_mode not in ("cyclic", "hashed"):
        raise ValueError("assignment_mode must be cyclic or hashed")
    return _voronoi_partition_codes(
        _voronoi_sites(seed, grid, jitter_percent, members, assignment_mode, member_shift))


class ConditioningLayersVoronoiPartitionField:
    RETURN_TYPES = ("MASK", "MASK", "MASK", "MASK")
    RETURN_NAMES = ("field_a", "field_b", "field_c", "field_d")
    FUNCTION = "generate"
    CATEGORY = "conditioning/conditioning_layers/fields"
    DESCRIPTION = (
        "Deterministic periodic Voronoi partition from grid x grid seeded sites. "
        "Each sample belongs to exactly one of the first members outputs; unused "
        "outputs are zero. Nonempty hard fields form exact FIXED partitions. "
        "Omit or disable empty Layer branches. Soft operations such as Blur, Fade "
        "or interpolated Transform may produce overlapping positive fields: use "
        "BLENDED for soft workflows, not overlapping FIXED layers."
    )

    @classmethod
    def INPUT_TYPES(cls):
        # One native number widget provides dragging/stepping and typed entry.
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 4294967295, "step": 1,
                             "display": "number", "control_after_generate": False,
                             "tooltip": "Fixed seed for versioned SHA-256 site positions and ownership."}),
            "grid": ("INT", {"default": 6, "min": 1, "max": 16, "step": 1,
                             "display": "number",
                             "tooltip": "One site per lattice cell: grid x grid sites."}),
            "jitter_percent": ("INT", {"default": 100, "min": 0, "max": 100, "step": 1,
                                       "display": "number",
                                       "tooltip": "Zero centers sites; 100 uses the full within-cell jitter range."}),
            "members": ("INT", {"default": 2, "min": 2, "max": 4, "step": 1,
                                "display": "number",
                                "tooltip": "First 2, 3 or 4 outputs participate. Omit or disable empty branches."}),
            "assignment_mode": (["cyclic", "hashed"], {"default": "cyclic",
                                "tooltip": "Row-major cyclic ownership or seeded multiply-high assignment."}),
            "member_shift": ("INT", {"default": 0, "min": 0, "max": 3, "step": 1,
                                     "display": "number",
                                     "tooltip": "Rotate member labels modulo members; site geometry stays fixed."}),
        }}

    def generate(self, seed, grid, jitter_percent, members, assignment_mode, member_shift):
        return tuple(codes_to_mask(codes) for codes in voronoi_partition_field_codes(
            seed, grid, jitter_percent, members, assignment_mode, member_shift))


NOISE_FIELD_ALGORITHM = "conditioning-layers.noise-field.v1"


def _noise_ratio(name, value, low, high):
    if (type(value) not in (int, float) or not low <= value <= high
            or not math.isfinite(value)):
        raise ValueError(f"{name} must be finite in [{low}, {high}]")
    return value.as_integer_ratio()


def _noise_lattice_word(seed, octave, ix, iy):
    digest = hashlib.sha256(
        f"{NOISE_FIELD_ALGORITHM}:{seed}:{octave}:{ix}:{iy}".encode("ascii")
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _noise_axis(lattice, offset_ratio):
    """Wrapped corner indices and exact smoothstep numerators at cell centers.

    Positive offset shifts the field right/down: sample (cell+.5-offset).
    One common denominator per axis works for every sample and octave.
    """
    numerator, denominator = offset_ratio
    d = 256 * denominator
    axis = []
    for cell in range(128):
        index, r = divmod(((2 * cell + 1) * denominator - 2 * numerator) * lattice, d)
        axis.append((index % lattice, (index + 1) % lattice, r * r * (3 * d - 2 * r)))
    return axis, d**3


def noise_field_codes(seed, frequency, octaves, persistence, offset_x, offset_y):
    """Periodic value noise, exact integers until one final half-up code rounding.

    FLOAT controls accept finite binary64 values (UI steps are adjustment hints).
    Treat those values as exact dyadic rationals. No per-image normalization,
    intermediate quantization, RNG, persistent cache or host arithmetic.
    """
    _integer("seed", seed, 0, 4294967295)
    _integer("octaves", octaves, 1, 6)
    fn, fd = _noise_ratio("frequency", frequency, 0.5, 32.0)
    pn, pd = _noise_ratio("persistence", persistence, 0.0, 1.0)
    ox = _noise_ratio("offset_x", offset_x, -128.0, 128.0)
    oy = _noise_ratio("offset_y", offset_y, -128.0, 128.0)
    base_lattice = (2 * fn + fd) // (2 * fd)
    if pn == 0:
        octaves = 1
    # Scale all p**o by the same pd**(octaves-1); it cancels at normalization.
    amplitudes = [pn**o * pd**(octaves - 1 - o) for o in range(octaves)]
    accumulated = [0] * 16384
    for octave, amplitude in enumerate(amplitudes):
        lattice = base_lattice * 2**octave
        xs, xd = _noise_axis(lattice, ox)
        ys, yd = _noise_axis(lattice, oy)
        # Only needed corners, each hashed once in this octave/call. At high
        # frequency most lattice points are never sampled; don't allocate them.
        columns = {corner for left, right, _ in xs for corner in (left, right)}
        rows = {corner for top, bottom, _ in ys for corner in (top, bottom)}
        words = {(i, j): _noise_lattice_word(seed, octave, i, j)
                 for j in rows for i in columns}
        for y, (top, bottom, sy) in enumerate(ys):
            for x, (left, right, sx) in enumerate(xs):
                upper = words[left, top] * (xd - sx) + words[right, top] * sx
                lower = words[left, bottom] * (xd - sx) + words[right, bottom] * sx
                accumulated[y * 128 + x] += amplitude * (upper * (yd - sy) + lower * sy)
    denominator = (2**64 - 1) * xd * yd * sum(amplitudes)
    return tuple(min(255, max(0, (510 * value + denominator) // (2 * denominator)))
                 for value in accumulated)


class ConditioningLayersNoiseField:
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "generate"
    CATEGORY = "conditioning/conditioning_layers/fields"
    DESCRIPTION = (
        "Deterministic seamless grayscale value noise with smoothstep interpolation. "
        "Frequency rounds half upward to a periodic lattice count, doubled each octave. "
        "A one-point lattice is constant at that octave. Use Remap, Blur or Fade for "
        "organic BLENDED fields. For complementary FIXED partitions, Remap threshold "
        "with input_low=t-1, input_high=t, output_low=0, output_high=255, then Invert."
    )

    @classmethod
    def INPUT_TYPES(cls):
        # Each native number widget supports dragging and direct typed entry.
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 4294967295, "step": 1,
                             "display": "number", "control_after_generate": False,
                             "tooltip": "Fixed seed for conditioning-layers.noise-field.v1 SHA-256 lattice values."}),
            "frequency": ("FLOAT", {"default": 4.0, "min": 0.5, "max": 32.0, "step": 0.5,
                                    "display": "number",
                                    "tooltip": "Base lattice periods per 128 cells, rounded half upward: 4.0 -> 4, 4.5 -> 5. One period is constant at that octave."}),
            "octaves": ("INT", {"default": 4, "min": 1, "max": 6, "step": 1,
                                "display": "number",
                                "tooltip": "Number of octaves; lattice count doubles each octave."}),
            "persistence": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                                      "display": "number",
                                      "tooltip": "Successive amplitude multiplier; normalized by amplitude sum, never image min/max. Zero keeps only octave 0."}),
            "offset_x": ("FLOAT", {"default": 0.0, "min": -128.0, "max": 128.0, "step": 1.0,
                                   "display": "number",
                                   "tooltip": "Field-cell translation: positive shifts right. Wraps every 128 cells."}),
            "offset_y": ("FLOAT", {"default": 0.0, "min": -128.0, "max": 128.0, "step": 1.0,
                                   "display": "number",
                                   "tooltip": "Field-cell translation: positive shifts down. Wraps every 128 cells."}),
        }}

    def generate(self, seed, frequency, octaves, persistence, offset_x, offset_y):
        return (codes_to_mask(noise_field_codes(
            seed, frequency, octaves, persistence, offset_x, offset_y)),)


def polar_partition_field_codes(center_x, center_y, rings, sectors, members,
                                radial_shift, angular_shift, assignment_mode):
    """Four binary planes from sample-center polar geometry on canvas edges.

    Spiral applies continuous radial phase before angular quantization. All
    geometry is call-local Python binary64; MASK encoding remains separate.
    """
    for name, value in (("center_x", center_x), ("center_y", center_y)):
        if (type(value) not in (int, float) or not 0 <= value <= 1
                or not math.isfinite(value)):
            raise ValueError(f"{name} must be finite in [0.0, 1.0]")
    for name, value, low, high in (
        ("rings", rings, 1, 32), ("sectors", sectors, 1, 64),
        ("members", members, 2, 4), ("radial_shift", radial_shift, 0, 3),
        ("angular_shift", angular_shift, 0, 63),
    ):
        _integer(name, value, low, high)
    if assignment_mode not in ("radial", "angular", "checker", "spiral"):
        raise ValueError("assignment_mode must be radial, angular, checker or spiral")

    cx, cy = center_x * 128, center_y * 128
    r_max = max(math.hypot(cx - x, cy - y) for x, y in
                ((0, 0), (128, 0), (0, 128), (128, 128)))
    fields = [[0] * 16384 for _ in range(4)]
    for y in range(128):
        dy = y + 0.5 - cy
        for x in range(128):
            dx = x + 0.5 - cx
            r = math.sqrt(dx * dx + dy * dy)
            rn = min(1.0, max(0.0, r / r_max))
            ring_index = min(rings - 1, math.floor(rn * rings))
            angle = 0.0 if dx == 0 and dy == 0 else math.atan2(dy, dx) % math.tau
            angular_position = angle / math.tau * sectors
            sector_index = min(sectors - 1, math.floor(angular_position))
            shifted_sector = (sector_index + angular_shift) % sectors
            if assignment_mode == "radial":
                owner = (ring_index + radial_shift) % members
            elif assignment_mode == "angular":
                owner = (shifted_sector + radial_shift) % members
            elif assignment_mode == "checker":
                owner = (ring_index + shifted_sector + radial_shift) % members
            else:
                spiral_position = (angular_position - rn * rings) % sectors
                spiral_sector = min(sectors - 1, math.floor(spiral_position))
                shifted_spiral_sector = (spiral_sector + angular_shift) % sectors
                owner = (shifted_spiral_sector + radial_shift) % members
            fields[owner][y * 128 + x] = 255
    return tuple(tuple(codes) for codes in fields)


class ConditioningLayersPolarPartitionField:
    RETURN_TYPES = ("MASK", "MASK", "MASK", "MASK")
    RETURN_NAMES = ("field_a", "field_b", "field_c", "field_d")
    FUNCTION = "generate"
    CATEGORY = "conditioning/conditioning_layers/fields"
    DESCRIPTION = (
        "Exact binary radial, angular, checker or continuous-phase spiral partition. "
        "Each sample has one owner among the first members outputs; unused outputs "
        "are zero. Nonempty hard fields form exact FIXED partitions. Omit or disable "
        "empty Layer branches. Fade alone preserves zero support; Blur or interpolating "
        "Transform may create positive overlaps. Use BLENDED for soft transitions; "
        "simultaneous FIXED layers require disjoint positive support."
    )

    @classmethod
    def INPUT_TYPES(cls):
        # Each native number widget supports dragging and direct typed entry.
        return {"required": {
            "center_x": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
                                   "display": "number",
                                   "tooltip": "Authored X center across canvas edges: 0 -> 0, 0.5 -> 64, 1 -> 128."}),
            "center_y": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
                                   "display": "number",
                                   "tooltip": "Authored Y center across canvas edges, increasing downward."}),
            "rings": ("INT", {"default": 4, "min": 1, "max": 32, "step": 1,
                              "display": "number",
                              "tooltip": "Radial divisions to the farthest outer corner; in spiral, continuous phase advances this many sector widths."}),
            "sectors": ("INT", {"default": 8, "min": 1, "max": 64, "step": 1,
                                "display": "number",
                                "tooltip": "Equal angular sectors, clockwise from right. Spiral turns = rings/sectors."}),
            "members": ("INT", {"default": 2, "min": 2, "max": 4, "step": 1,
                                "display": "number",
                                "tooltip": "First 2, 3 or 4 outputs participate. Omit or disable empty branches."}),
            "radial_shift": ("INT", {"default": 0, "min": 0, "max": 3, "step": 1,
                                     "display": "number",
                                     "tooltip": "Shift member labels modulo members in every mode; geometry stays fixed."}),
            "angular_shift": ("INT", {"default": 0, "min": 0, "max": 63, "step": 1,
                                      "display": "number",
                                      "tooltip": "Shift sector indexing modulo sectors; in spiral, after phase quantization."}),
            "assignment_mode": (["radial", "angular", "checker", "spiral"], {"default": "checker",
                                "tooltip": "Rings, spokes, dartboard, or continuous radial-phase spiral rotating clockwise outward."}),
        }}

    def generate(self, center_x, center_y, rings, sectors, members,
                 radial_shift, angular_shift, assignment_mode):
        return tuple(codes_to_mask(codes) for codes in polar_partition_field_codes(
            center_x, center_y, rings, sectors, members, radial_shift, angular_shift, assignment_mode))


def initialize_procedural_field_node_registration():
    """Fresh mappings; importing and registering requires no tensor runtime."""
    return ({"ConditioningLayersScatterField": ConditioningLayersScatterField,
             "ConditioningLayersCyclicPartitionField": ConditioningLayersCyclicPartitionField,
             "ConditioningLayersVoronoiPartitionField": ConditioningLayersVoronoiPartitionField,
             "ConditioningLayersNoiseField": ConditioningLayersNoiseField,
             "ConditioningLayersPolarPartitionField": ConditioningLayersPolarPartitionField},
            {"ConditioningLayersScatterField": "Scatter Field",
             "ConditioningLayersCyclicPartitionField": "Cyclic Partition Field",
             "ConditioningLayersVoronoiPartitionField": "Voronoi Partition Field",
             "ConditioningLayersNoiseField": "Noise Field",
             "ConditioningLayersPolarPartitionField": "Polar Partition Field"})
