import { rangeOptions } from "$lib/chart";

/** A fixed span of absolute times, in ms since epoch, and what set it. */
export type Span = { from: number; to: number; by: "pause" | "zoom" };

let created = 0;

/**
 * One instance's set of panels: which range they show, and whether they follow new readings.
 * - Live: the range ending at the newest reading, sliding with each poll.
 * - Fixed: a span of absolute times set by Pause or by a zoom; new readings don't move it.
 * - A fixed span only sets the x-axis. Readings keep arriving as usual; there's no frozen copy of them.
 */
export class Dashboard {
  /** Joins the panels' crosshairs. A counter, since crypto.randomUUID needs a secure context and http on a LAN isn't one. */
  readonly syncKey = `dashboard-${++created}`;
  /** How far back the history goes, from the history response. */
  historyMinutes = $state(30);
  /** When the newest reading was taken, in ms since epoch. */
  end = $state(Date.now());
  span = $state<Span | null>(null);
  #picked = $state<number | null>(null);

  readonly options = $derived(rangeOptions(this.historyMinutes));
  /** Minutes shown while live: the range picked, while it's still offered, or else the longest offered. */
  readonly range = $derived(
    this.#picked !== null && this.options.includes(this.#picked) ? this.#picked : this.options[this.options.length - 1],
  );
  readonly button = $derived(this.span === null ? "Pause" : this.span.by === "pause" ? "Resume" : "Reset zoom");
  readonly window: { from: number; to: number } = $derived(
    this.span ?? { from: this.end - this.range * 60_000, to: this.end },
  );

  pick(minutes: number) {
    this.#picked = minutes;
    this.span = null;
  }

  pause() {
    this.span = { ...this.window, by: "pause" };
  }

  /** Zooms to a span inside what's shown now, so zooming while zoomed or paused narrows it. */
  zoom(from: number, to: number) {
    const shown = this.window;
    const span = { from: Math.max(from, shown.from), to: Math.min(to, shown.to) };
    if (span.to > span.from) this.span = { ...span, by: "zoom" };
  }

  live() {
    this.span = null;
  }
}
