// E4 gradient value profiles: the code a stamp moves each covered cell toward. No host imports
// or import-time work. The footprint (brush.js) decides where and how strongly a stamp covers
// cells; the value profile decides only the target. Uniform keeps E1's single target and has
// no prepared profile.
//
// Frame (design record §9): the brush-local position from footprintLocal divided by the crop
// rectangle's half extents, so the cropped footprint spans [-1,1]^2 (x right, y down) before
// its mirror, scale and rotation, which therefore carry the profile with the brush. An
// uncropped disk's edge is the unit circle.
//   linear  rho = 50 (u cos a + v sin a + 1)    % along the axis: 0 and 100 on the unit circle
//   radial  rho = 100 sqrt(x'^2 + y'^2)         % of the unit circle
//   square  rho = 100 max(|x'|, |y'|)
//   (x', y') = (u, v) less Center, turned back by Rotation, divided by Aspect X/Y
//   t = clamp((rho - from) / (to - from), 0, 1)  from/to: Start/End Position, or Inner/Outer
//   T = q(Start + t^Curve (End - Start))          q rounds half up, once
// Angles are clockwise. Multiples of 45 degrees use exact axes, as Field Fade does; any other
// angle uses Math.cos/Math.sin once, when the profile is prepared.

function nearest(value) {
  const floor = Math.floor(value);
  return floor + (value - floor >= 0.5 ? 1 : 0);
}

function axis(degrees) {
  const angle = (degrees % 360 + 360) % 360;
  if (angle % 45 === 0) {
    const h = Math.sqrt(0.5);
    return [[1, 0], [h, h], [0, 1], [-h, h], [-1, 0], [-h, -h], [0, -1], [h, -h]][angle / 45];
  }
  const radians = angle * (Math.PI / 180);
  return [Math.cos(radians), Math.sin(radians)];
}

// t^c for 0 <= t <= 1 from products and square roots only, like E3's Flow power, so engines
// agree: the whole part of c multiplies t in, then the binary digits of its fraction select
// t^(1/2), t^(1/4), ... in turn.
export function curvePower(t, c) {
  let result = 1, fraction = c - Math.floor(c);
  for (let k = Math.floor(c); k > 0; k--) result *= t;
  for (let root = t; fraction > 0 && root < 1;) {
    root = Math.sqrt(root); fraction *= 2;
    if (fraction >= 1) { result *= root; fraction -= 1; }
  }
  return result;
}

// The target code at transition coordinate t: the definition.
export function gradientCode(start, end, curve, t) {
  return nearest(start + curvePower(t, curve) * (end - start));
}

// The least t at which gradientCode reaches each code past Start, found by bisection with the
// definition itself, which is monotone in t. A lookup therefore equals the definition exactly,
// and a fractional Curve costs nothing per cell. The last parameters' table is kept.
let memo = null;
function codeLevels(start, end, curve) {
  const key = `${start} ${end} ${curve}`;
  if (memo?.key === key) return memo.levels;
  const step = Math.sign(end - start), levels = new Float64Array(Math.abs(end - start));
  let low = 0; // never reaches the next code: gradientCode(.., 0) is Start
  for (let k = 0; k < levels.length; k++) {
    const code = start + step * (k + 1);
    let high = 1;
    for (let middle = (low + high) / 2; middle !== low && middle !== high; middle = (low + high) / 2) {
      if (step * (gradientCode(start, end, curve, middle) - code) >= 0) high = middle;
      else low = middle;
    }
    levels[k] = high;
  }
  memo = {key, levels};
  return levels;
}

// Everything a stamp's profile needs, computed once per stroke or preview; null for Uniform.
// b holds resolved settings (resolveBrush), f the prepared footprint.
export function prepareProfile(b, f) {
  if (b.value_profile === "uniform") return null;
  const p = {kind: b.value_profile, halfX: f.halfX, halfY: f.halfY, start: b.gradient_start,
    step: Math.sign(b.gradient_end - b.gradient_start),
    levels: codeLevels(b.gradient_start, b.gradient_end, b.gradient_curve)};
  if (p.kind === "linear") {
    [p.cos, p.sin] = axis(b.gradient_angle);
    p.from = b.gradient_start_position; p.span = b.gradient_end_position - b.gradient_start_position;
  } else {
    p.centerX = (b.gradient_center_x - 50) / 50; p.centerY = (b.gradient_center_y - 50) / 50;
    p.aspectX = b.gradient_aspect_x; p.aspectY = b.gradient_aspect_y;
    // A true circle ignores Rotation, which keeps it exactly rotation invariant (as Field Fade).
    [p.cos, p.sin] = axis(p.kind === "radial" && p.aspectX === p.aspectY ? 0 : b.gradient_rotation);
    p.from = b.gradient_inner; p.span = b.gradient_outer - b.gradient_inner;
  }
  return p;
}

// Transition coordinate t, 0..1, at brush-local (x, y) in cells from the crop centre.
export function profileTransition(p, x, y) {
  const u = x / p.halfX, v = y / p.halfY;
  let rho;
  if (p.kind === "linear") rho = 50 * (u * p.cos + v * p.sin + 1);
  else {
    const du = u - p.centerX, dv = v - p.centerY;
    const lx = (p.cos * du + p.sin * dv) / p.aspectX, ly = (-p.sin * du + p.cos * dv) / p.aspectY;
    rho = 100 * (p.kind === "radial" ? Math.sqrt(lx * lx + ly * ly) : Math.max(Math.abs(lx), Math.abs(ly)));
  }
  const t = (rho - p.from) / p.span;
  return t <= 0 ? 0 : t >= 1 ? 1 : t;
}

// gradientCode(Start, End, Curve, t), exactly, by counting the levels at or below t.
export function transitionCode(p, t) {
  const levels = p.levels;
  let low = 0, high = levels.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (levels[middle] <= t) low = middle + 1;
    else high = middle;
  }
  return p.start + p.step * low;
}

// Target code at brush-local (x, y).
export function profileTarget(p, x, y) {
  return transitionCode(p, profileTransition(p, x, y));
}
