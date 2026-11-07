/** Motion stays short (at most 250 ms), shares two curves with app.css, and stops entirely when the system asks for less. */

const LONGEST_MS = 250;

export function prefersReducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** A duration for Svelte transitions: 0 under reduced motion. */
export function duration(ms: number): number {
  return prefersReducedMotion() ? 0 : Math.min(ms, LONGEST_MS);
}

/** A CSS cubic-bezier as a Svelte easing function: solve x(s) = t, then return y(s). */
function cubicBezier(x1: number, y1: number, x2: number, y2: number): (t: number) => number {
  const cx = 3 * x1;
  const bx = 3 * (x2 - x1) - cx;
  const ax = 1 - cx - bx;
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  const x = (s: number) => ((ax * s + bx) * s + cx) * s;
  const y = (s: number) => ((ay * s + by) * s + cy) * s;
  const slope = (s: number) => (3 * ax * s + 2 * bx) * s + cx;
  return (t) => {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    // Newton's method converges in a few steps; bisection is the fallback where the slope flattens.
    let s = t;
    for (let i = 0; i < 8; i++) {
      const error = x(s) - t;
      if (Math.abs(error) < 1e-7) return y(s);
      const d = slope(s);
      if (Math.abs(d) < 1e-7) break;
      s -= error / d;
    }
    let lo = 0;
    let hi = 1;
    s = t;
    while (hi - lo > 1e-7) {
      if (x(s) < t) lo = s;
      else hi = s;
      s = (lo + hi) / 2;
    }
    return y(s);
  };
}

/** Entering, leaving, opening, closing. Same curve as `--ease-out` in app.css. */
export const easeOut = cubicBezier(0.23, 1, 0.32, 1);

/** Moving or changing size in place. Same curve as `--ease-in-out` in app.css. */
export const easeInOut = cubicBezier(0.77, 0, 0.175, 1);

/** How long something that just changed state stays tinted before its 250 ms fade. A pause, not motion. */
export const FLASH_HOLD_MS = 1500;
