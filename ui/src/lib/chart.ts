/** Lines for the hand-drawn SVG charts. Points are in SVG units; null is a missing reading. */

export type Point = { x: number; y: number } | null;

/** An SVG path through the points, broken at every null. A lone point draws as a dot (round caps). */
export function linePath(points: Point[]): string {
  const parts: string[] = [];
  let run = 0;
  for (const point of points) {
    if (!point) {
      if (run === 1) parts.push("h0");
      run = 0;
      continue;
    }
    parts.push(`${run === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`);
    run++;
  }
  if (run === 1) parts.push("h0");
  return parts.join(" ");
}

/** A round top for a chart's scale at or above `value`: 1, 2 or 5 times a power of ten. */
export function niceMax(value: number): number {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 5]) if (value <= step * power * (1 + 1e-9)) return Number((step * power).toPrecision(12));
  return Number((10 * power).toPrecision(12));
}

/** Where a value sits in a chart `height` tall: 0 at the bottom, `max` at the top, room for the stroke. */
export function yFor(value: number, max: number, height: number): number {
  const share = max > 0 ? Math.min(Math.max(value / max, 0), 1) : 0;
  return height - share * (height - 3) - 1.5;
}
