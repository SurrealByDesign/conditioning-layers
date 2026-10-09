// Shared E5 bilinear sampler. Pixel centres are (i + 1/2, j + 1/2).
// Caller checks the mask rectangle; edge neighbours clamp inside it.
export function sampleTip(mask, px, py) {
  const {codes, width, height} = mask, fx = px - 0.5, fy = py - 0.5;
  const x0 = Math.floor(fx), y0 = Math.floor(fy), tx = fx - x0, ty = fy - y0;
  const xa = x0 < 0 ? 0 : x0 < width ? x0 : width - 1, xb = x0 < -1 ? 0 : x0 + 1 < width ? x0 + 1 : width - 1;
  const ya = (y0 < 0 ? 0 : y0 < height ? y0 : height - 1) * width;
  const yb = (y0 < -1 ? 0 : y0 + 1 < height ? y0 + 1 : height - 1) * width;
  const top = codes[ya + xa] + tx * (codes[ya + xb] - codes[ya + xa]);
  const bottom = codes[yb + xa] + tx * (codes[yb + xb] - codes[yb + xa]);
  return top + ty * (bottom - top);
}
