/** Theme colours for canvas drawing. A canvas can't use CSS variables, so charts read them when they draw. */

import type { SeriesColor } from "$lib/chart";

/** A CSS variable's current value on the page root, such as `--border`. */
export function cssColor(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** The current colour of a series token, `--series-N`. */
export function seriesColor(color: SeriesColor): string {
  return cssColor(`--series-${color}`);
}

/** A `#rrggbb` colour at the given opacity; any other colour comes back as it is. */
export function alpha(color: string, opacity: number): string {
  const hex = /^#([0-9a-f]{6})$/i.exec(color);
  if (!hex) return color;
  const n = parseInt(hex[1], 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${opacity})`;
}
