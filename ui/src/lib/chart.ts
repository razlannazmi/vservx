/** Chart helpers: lines for the small SVG trends, and the data shaping behind the uPlot panels.
 * Null is always a missing reading. */

import type { ThresholdMetric, UsagePointRead } from "$lib/api/client";

/** Range choices, in minutes; only those the history window covers are offered. */
export const RANGE_PRESETS = [5, 15, 30, 60, 180, 360, 720, 1440];

/** The presets the history window covers, then the window itself when it isn't a preset, so all of it can be shown. */
export function rangeOptions(historyMinutes: number): number[] {
  const fitting = RANGE_PRESETS.filter((minutes) => minutes <= historyMinutes);
  return fitting.includes(historyMinutes) ? fitting : [...fitting, historyMinutes];
}

export type Stats = { last: number | null; min: number | null; max: number | null; mean: number | null };

/** Last, min, max and mean of the readings there are; all null when there are none. */
export function seriesStats(values: (number | null)[]): Stats {
  const present = values.filter((value): value is number => value !== null);
  if (present.length === 0) return { last: null, min: null, max: null, mean: null };
  return {
    last: present[present.length - 1],
    min: Math.min(...present),
    max: Math.max(...present),
    mean: present.reduce((sum, value) => sum + value, 0) / present.length,
  };
}

export type ThresholdState = "ok" | "warning" | "critical";

/** Where a reading stands against its thresholds: above critical, above warning, or neither. */
export function thresholdState(value: number | null, warning: number | null, critical: number | null): ThresholdState {
  if (value === null) return "ok";
  if (critical !== null && value > critical) return "critical";
  if (warning !== null && value > warning) return "warning";
  return "ok";
}

/** Which of the `--series-N` colour tokens a series is drawn in. */
export type SeriesColor = 1 | 2 | 3 | 4 | 5;

/** One line on a panel: its legend name, colour, how to read it from a reading, and the threshold
 * metric it carries, if any. */
export type SeriesSpec = {
  key: string;
  label: string;
  color: SeriesColor;
  value: (point: UsagePointRead) => number | null;
  metric?: ThresholdMetric;
};

/** uPlot's data: times in seconds, then one array of values per series. */
export type Columns = [number[], ...(number | null)[][]];

/** The readings from `from` to `to` (ms since epoch, both included), as uPlot columns. */
export function toColumns(points: UsagePointRead[], series: SeriesSpec[], from: number, to: number): Columns {
  const shown = points.filter((point) => {
    const at = Date.parse(point.at);
    return at >= from && at <= to;
  });
  return [shown.map((point) => Date.parse(point.at) / 1000), ...series.map((each) => shown.map(each.value))];
}

/**
 * Whether the backend kept readings between two the page got, given how often it reads.
 * - More than one and a half intervals apart: a hidden tab or a late poll skipped one.
 * - Less is the usual jitter of a poll.
 */
export function missedReadings(lastAt: string, latestAt: string, intervalSeconds: number): boolean {
  return Date.parse(latestAt) - Date.parse(lastAt) > intervalSeconds * 1500;
}

/** An axis number: "1.2k" and "25k" from a thousand up, and up to two decimals below, so ticks 0.25 apart don't all read "0". */
export function shortNumber(value: number): string {
  if (Math.abs(value) >= 1000) {
    return `${(value / 1000).toLocaleString(undefined, { maximumFractionDigits: Math.abs(value) >= 10_000 ? 0 : 1 })}k`;
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

const pad = (n: number) => String(n).padStart(2, "0");

/** A local clock time for `seconds` since epoch: "14:05", or "14:05:30" when ticks are under a minute apart. */
export function timeLabel(seconds: number, step: number): string {
  const at = new Date(seconds * 1000);
  const minutes = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  return step < 60 ? `${minutes}:${pad(at.getSeconds())}` : minutes;
}

/**
 * The widest of `values` drawn in `font`, in CSS pixels.
 * - Puts the canvas font back afterwards: uPlot skips setting a font it thinks is already set.
 */
export function textWidth(ctx: Pick<CanvasRenderingContext2D, "font" | "measureText">, font: string, values: string[]): number {
  const previous = ctx.font;
  ctx.font = font;
  const widest = Math.max(0, ...values.map((value) => ctx.measureText(value).width));
  ctx.font = previous;
  return widest;
}

/** A point of a small SVG trend line, in SVG units. */
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
