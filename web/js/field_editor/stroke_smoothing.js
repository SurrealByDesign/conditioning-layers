// Stroke smoothing. No imports or import-time work. It reshapes the sampled pointer path before a
// stroke receives it; stamp placement, spacing and field arithmetic stay the stroke's own.
//
// The smoothed point follows the pointer by distance travelled, never by time or event count:
// over pointer travel h it closes the share h / (L + h) of its gap to the pointer, where the reach
// L is Smoothing / 100 x SMOOTHING_REACH cells. Each pointer segment is walked in equal steps of at
// most SMOOTHING_STEP cells, so the path a stroke receives hardly depends on how often pointer
// events arrive. A pointer at rest moves nothing; finish() runs straight on to the pointer, so a
// stroke ends where it was released. Only +, -, *, /, Math.sqrt, Math.ceil and Math.round are
// used, so the path is exactly specified. Smoothing 0 passes every point through unchanged.
export const SMOOTHING_REACH = 8;
export const SMOOTHING_STEP = 0.25;

export class StrokeSmoother {
  // emit(x, y, pressure) receives each point; pressure is a pen pressure code, or null without one.
  constructor(smoothing, x, y, pressure, emit) {
    if (!Number.isInteger(smoothing) || smoothing < 0 || smoothing > 100) throw new Error("Invalid smoothing");
    this.reach = smoothing * SMOOTHING_REACH / 100;
    this.pointer = [x, y]; this.point = [x, y]; this.pressure = pressure; this.emit = emit;
  }

  add(x, y, pressure = null) {
    if (this.reach === 0) { this.pointer = [x, y]; this.point = [x, y]; this.pressure = pressure; this.emit(x, y, pressure); return; }
    const [px, py] = this.pointer, dx = x - px, dy = y - py, distance = Math.sqrt(dx * dx + dy * dy);
    const steps = Math.ceil(distance / SMOOTHING_STEP), from = this.pressure, point = this.point;
    if (steps === 0) {
      // At rest only a pressure change is passed on, at the smoothed point.
      if (pressure !== from) { this.pressure = pressure; this.emit(point[0], point[1], pressure); }
      return;
    }
    const h = distance / steps, share = h / (this.reach + h);
    for (let i = 1; i <= steps; i++) {
      point[0] += (px + dx * i / steps - point[0]) * share;
      point[1] += (py + dy * i / steps - point[1]) * share;
      this.emit(point[0], point[1], pressure === null ? null : from + Math.round((pressure - from) * i / steps));
    }
    this.pointer = [x, y]; this.pressure = pressure;
  }

  // The stroke's last point is the pointer's own.
  finish() {
    const [x, y] = this.pointer;
    if (this.point[0] !== x || this.point[1] !== y) { this.point = [x, y]; this.emit(x, y, this.pressure); }
  }
}
