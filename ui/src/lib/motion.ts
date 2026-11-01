/** Motion stays short (at most 250 ms) and stops entirely when the system asks for less. */

const LONGEST_MS = 250;

export function prefersReducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** A duration for Svelte transitions: 0 under reduced motion. */
export function duration(ms: number): number {
  return prefersReducedMotion() ? 0 : Math.min(ms, LONGEST_MS);
}
