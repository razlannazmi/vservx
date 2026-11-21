import { expect, test } from "vitest";
import type { UsagePointRead } from "$lib/api/client";
import {
  rangeOptions,
  seriesStats,
  shortNumber,
  textWidth,
  thresholdState,
  timeLabel,
  toColumns,
  type SeriesSpec,
} from "$lib/chart";

test("shortNumber keeps small fractions and shortens thousands", () => {
  expect([0, 0.25, 0.5, 3].map(shortNumber)).toEqual(["0", "0.25", "0.5", "3"]);
  expect([1200, 25_000].map(shortNumber)).toEqual(["1.2k", "25k"]);
});

test("thresholdState is strictly above, critical first", () => {
  expect(thresholdState(90, 90, 98)).toBe("ok");
  expect(thresholdState(90.1, 90, 98)).toBe("warning");
  expect(thresholdState(98, 90, 98)).toBe("warning");
  expect(thresholdState(99, 90, 98)).toBe("critical");
  expect(thresholdState(99, null, 98)).toBe("critical");
  expect(thresholdState(null, 90, 98)).toBe("ok");
  expect(thresholdState(50, null, null)).toBe("ok");
});

test("timeLabel shows seconds only when ticks are under a minute apart", () => {
  const at = new Date(2026, 10, 15, 14, 5, 30).getTime() / 1000;
  expect(timeLabel(at, 60)).toBe("14:05");
  expect(timeLabel(at, 30)).toBe("14:05:30");
});

test("textWidth measures in the given font and puts the canvas font back", () => {
  const fonts: string[] = [];
  const ctx = {
    font: "22px Geist",
    measureText(text: string) {
      fonts.push(this.font);
      return { width: text.length * 5 } as TextMetrics;
    },
  };
  expect(textWidth(ctx, "11px Geist", ["4 req", "12 req"])).toBe(30);
  expect(fonts).toEqual(["11px Geist", "11px Geist"]);
  expect(ctx.font).toBe("22px Geist");
});

test("seriesStats ignores gaps", () => {
  expect(seriesStats([2, null, 6, 4, null])).toEqual({ last: 4, min: 2, max: 6, mean: 4 });
  expect(seriesStats([])).toEqual({ last: null, min: null, max: null, mean: null });
  expect(seriesStats([null, null])).toEqual({ last: null, min: null, max: null, mean: null });
});

test("rangeOptions", () => {
  expect(rangeOptions(30)).toEqual([5, 15, 30]);
  expect(rangeOptions(60)).toEqual([5, 15, 30, 60]);
  expect(rangeOptions(45)).toEqual([5, 15, 30, 45]);
  expect(rangeOptions(2)).toEqual([2]);
});

test("toColumns keeps the window and its gaps", () => {
  const at = (s: number) => new Date(s * 1000).toISOString();
  const points = [10, 20, 30].map((s, i) => ({ at: at(s), running: i === 1 ? null : i, waiting: 0 }) as UsagePointRead);
  const series: SeriesSpec[] = [{ key: "running", label: "running", color: 1, value: (p) => p.running }];
  expect(toColumns(points, series, 20_000, 30_000)).toEqual([[20, 30], [null, 2]]);
  expect(toColumns([], series, 0, 1)).toEqual([[], []]);
});
