<script lang="ts" module>
  let panels = 0;
  // The panel under the pointer or the last tap: only it shows a tooltip, while the others mark the moment.
  let active: string | null = null;
</script>

<script lang="ts">
  import EllipsisIcon from "@lucide/svelte/icons/ellipsis";
  import Maximize2Icon from "@lucide/svelte/icons/maximize-2";
  import Minimize2Icon from "@lucide/svelte/icons/minimize-2";
  import { mode } from "mode-watcher";
  import { untrack } from "svelte";
  import { innerHeight } from "svelte/reactivity/window";
  import uPlot from "uplot";
  import "uplot/dist/uPlot.min.css";
  import type { UsagePointRead } from "$lib/api/client";
  import { niceMax, seriesStats, textWidth, timeLabel, toColumns, type SeriesColor, type SeriesSpec } from "$lib/chart";
  import { alpha, cssColor, seriesColor } from "$lib/charts/colors";
  import type { Dashboard } from "$lib/charts/dashboard.svelte";
  import TimeSeriesPanel from "$lib/components/charts/TimeSeriesPanel.svelte";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { phone } from "$lib/layout.svelte";

  // One metric over the dashboard's window, drawn by uPlot, with a stats legend under it.
  // - The canvas is hidden from assistive technology; the legend table carries the numbers.
  // - Every panel with the same dashboard shares a crosshair and a zoom.
  // - Colours are read from the theme each time the chart draws, so a theme switch only needs a redraw.
  let {
    title,
    unit,
    format,
    tick,
    points,
    series,
    max,
    dashboard,
    height = 150,
    fullscreen = false,
  }: {
    title: string;
    unit: string;
    format: (value: number) => string;
    tick?: (value: number) => string;
    points: UsagePointRead[];
    series: SeriesSpec[];
    max?: number;
    dashboard: Dashboard;
    height?: number;
    fullscreen?: boolean;
  } = $props();

  type Publishing = uPlot & { setCursor(opts: { left: number; top: number }, fire: boolean, publish: boolean): void };

  const FONT = "11px 'Geist Variable', system-ui, sans-serif";
  const id = `panel-${++panels}`;

  let container: HTMLDivElement;
  let chart = $state.raw<uPlot | null>(null);
  let expanded = $state(false);
  let viewing = $state(false);
  let hidden = $state<string[]>([]);
  let tip = $state<{ left: number; flip: boolean; time: string; rows: { label: string; color: SeriesColor; value: string }[] } | null>(
    null,
  );

  const chartHeight = $derived(expanded && !phone.current ? 260 : height);
  const columns = $derived(toColumns(points, series, dashboard.window.from, dashboard.window.to));
  const stats = $derived(series.map((_, i) => seriesStats(columns[i + 1])));
  const keys = $derived(series.map((each) => each.key).join(","));
  // What the x-axis spans; uPlot reads it each time it ranges the scale.
  let shown = untrack(() => dashboard.window);

  const show = (value: number | null | undefined) => (value === null || value === undefined ? "—" : format(value));

  // A chart per set of series; a phone gets one without drag-to-zoom.
  $effect(() => {
    void keys;
    const touch = phone.current;
    const made = untrack(() => new uPlot(options(touch), columns, container));
    chart = made;
    const resize = new ResizeObserver(() => made.setSize({ width: container.clientWidth, height: untrack(() => chartHeight) }));
    resize.observe(container);
    const unbind = listen(made);
    return () => {
      unbind();
      resize.disconnect();
      made.destroy();
      chart = null;
      tip = null;
    };
  });

  // uPlot ranges the x scale only when there's data, so an empty window is set by hand to keep its axis.
  $effect(() => {
    const data = columns;
    const window = dashboard.window;
    if (!chart) return;
    shown = window;
    chart.setData(data);
    if (data[0].length === 0) chart.setScale("x", { min: window.from / 1000, max: window.to / 1000 });
  });

  $effect(() => {
    const next = chartHeight;
    chart?.setSize({ width: container.clientWidth, height: next });
  });

  $effect(() => {
    const off = hidden;
    const made = chart;
    if (!made) return;
    series.forEach((each, i) => made.setSeries(i + 1, { show: !off.includes(each.key) }, false));
  });

  // mode-watcher switches the page's class first; the redraw waits a frame so it reads the new colours.
  $effect(() => {
    void mode.current;
    const made = chart;
    if (!made) return;
    requestAnimationFrame(() => {
      if (chart === made) made.redraw(true, true);
    });
  });

  function options(touch: boolean): uPlot.Options {
    const single = series.length === 1;
    const axis = {
      stroke: () => cssColor("--muted-foreground"),
      font: FONT,
      grid: { stroke: () => cssColor("--border"), width: 1 },
      ticks: { show: false },
    };
    return {
      width: container.clientWidth,
      height: chartHeight,
      legend: { show: false },
      padding: [8, 8, 0, 0],
      scales: {
        x: { time: true, range: () => [shown.from / 1000, shown.to / 1000] },
        y: { range: (_self, _min, dataMax) => [0, max ?? niceMax(Number.isFinite(dataMax) ? dataMax : 0)] },
      },
      axes: [
        {
          ...axis,
          size: 24,
          gap: 4,
          space: touch ? 80 : 60,
          values: (_self, splits, _axis, _space, step) => splits.map((each) => timeLabel(each, step)),
        },
        { ...axis, size: labelWidth, gap: 6, space: 28, values: (_self, splits) => splits.map((value) => (tick ?? format)(value)) },
      ],
      series: [
        {},
        ...series.map((each) => ({
          label: each.label,
          stroke: () => seriesColor(each.color),
          width: 1.5,
          spanGaps: false,
          fill: single ? () => alpha(seriesColor(each.color), 0.12) : undefined,
          points: { show: false },
        })),
      ],
      cursor: {
        sync: { key: dashboard.syncKey, setSeries: false },
        drag: touch ? { x: false, y: false, setScale: false } : { x: true, y: false, setScale: false, dist: 5 },
        points: { size: 7, width: 2, fill: () => cssColor("--card") },
        bind: {
          dblclick: () => () => {
            dashboard.live();
            return null;
          },
        },
      },
      hooks: {
        setSelect: [
          (self) => {
            if (self.select.width <= 0) return;
            const from = self.posToVal(self.select.left, "x") * 1000;
            const to = self.posToVal(self.select.left + self.select.width, "x") * 1000;
            self.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
            dashboard.zoom(from, to);
          },
        ],
        setCursor: [(self) => showTip(self)],
      },
    };
  }

  // The y-axis is as wide as its longest label, since labels carry units ("1.2k tok/s").
  function labelWidth(self: uPlot, values: string[] | null): number {
    if (!values || values.length === 0) return 40;
    return Math.ceil(textWidth(self.ctx, FONT, values)) + 14;
  }

  // A mouse makes this panel active while over it. A finger makes it active on touch, and a sideways
  // drag moves the crosshair while an up-down one still scrolls the page (touch-action: pan-y).
  function listen(made: uPlot): () => void {
    const over = made.over;
    over.style.touchAction = "pan-y";
    const enter = (event: PointerEvent) => {
      if (event.pointerType === "mouse") active = id;
    };
    const leave = (event: PointerEvent) => {
      if (event.pointerType === "mouse" && active === id) {
        active = null;
        tip = null;
      }
    };
    const follow = (event: PointerEvent) => {
      if (event.pointerType === "mouse") return;
      active = id;
      const box = over.getBoundingClientRect();
      // Fired and published, so the other panels mark the same moment and drop their tooltips.
      // - uPlot's setCursor takes a third "publish to the sync group" argument its types leave out.
      (made as Publishing).setCursor({ left: event.clientX - box.left, top: event.clientY - box.top }, true, true);
    };
    over.addEventListener("pointerenter", enter);
    over.addEventListener("pointerleave", leave);
    over.addEventListener("pointerdown", follow);
    over.addEventListener("pointermove", follow);
    return () => {
      over.removeEventListener("pointerenter", enter);
      over.removeEventListener("pointerleave", leave);
      over.removeEventListener("pointerdown", follow);
      over.removeEventListener("pointermove", follow);
    };
  }

  function showTip(made: uPlot) {
    const idx = made.cursor.idx;
    const left = made.cursor.left ?? -1;
    if (active !== id || idx === null || idx === undefined || left < 0) {
      tip = null;
      return;
    }
    const offset = made.over.getBoundingClientRect().left - container.getBoundingClientRect().left;
    tip = {
      left: offset + left,
      flip: left > made.over.clientWidth * 0.6,
      time: timeLabel(made.data[0][idx], 1),
      rows: series.flatMap((each, i) =>
        hidden.includes(each.key) ? [] : [{ label: each.label, color: each.color, value: show(made.data[i + 1][idx]) }],
      ),
    };
  }

  // A click hides or shows a series. Ctrl or ⌘ shows only that one, and the same again shows them all.
  function toggle(event: MouseEvent, key: string) {
    if (event.ctrlKey || event.metaKey) {
      const others = series.map((each) => each.key).filter((each) => each !== key);
      const alone = others.every((each) => hidden.includes(each)) && !hidden.includes(key);
      hidden = alone ? [] : others;
    } else {
      hidden = hidden.includes(key) ? hidden.filter((each) => each !== key) : [...hidden, key];
    }
  }
</script>

<div
  class="flex min-w-0 flex-col rounded-lg border bg-card px-3 py-2 {expanded && !fullscreen ? '@min-[40rem]:col-span-2' : ''}"
  role="group"
  aria-labelledby={id}
>
  <div class="flex items-center justify-between gap-2">
    <h4 {id} class="truncate text-xs font-semibold">
      {title}<span class="ml-1.5 font-normal text-muted-foreground">{unit}</span>
    </h4>
    <div class="-mr-1.5 flex shrink-0 items-center text-muted-foreground">
      {#if !fullscreen && !phone.current}
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={expanded ? `Shrink ${title}` : `Expand ${title}`}
          aria-pressed={expanded}
          onclick={() => (expanded = !expanded)}
        >
          {#if expanded}<Minimize2Icon />{:else}<Maximize2Icon />{/if}
        </Button>
      {/if}
      <DropdownMenu.Root>
        <DropdownMenu.Trigger class={buttonVariants({ variant: "ghost", size: "icon-xs" })} aria-label="{title} options">
          <EllipsisIcon />
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end">
          {#if !fullscreen}
            <DropdownMenu.Item onSelect={() => (viewing = true)}>View full screen</DropdownMenu.Item>
          {/if}
          <DropdownMenu.Item disabled={dashboard.span === null} onSelect={() => dashboard.live()}>Reset zoom</DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </div>
  </div>

  <div class="relative mt-1">
    <div bind:this={container} class="min-w-0" style:height="{chartHeight}px" aria-hidden="true"></div>
    {#if tip}
      <div
        class="pointer-events-none absolute top-1 z-10 rounded-md border bg-popover px-2 py-1 text-[11px] whitespace-nowrap text-popover-foreground tabular-nums shadow-sm"
        style:left="{tip.left}px"
        style:transform={tip.flip ? "translateX(calc(-100% - 8px))" : "translateX(8px)"}
        aria-hidden="true"
      >
        <div class="text-muted-foreground">{tip.time}</div>
        {#each tip.rows as row (row.label)}
          <div class="flex justify-between gap-3">
            <span class="inline-flex items-center gap-1.5">
              <i class="inline-block h-[3px] w-2.5 rounded-full" style:background="var(--series-{row.color})"></i>{row.label}
            </span>
            <span class="font-medium">{row.value}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <table class="mt-1.5 w-full text-[11px] tabular-nums">
    <thead>
      <tr class="text-muted-foreground">
        <th scope="col" class="text-left font-normal"><span class="sr-only">Series</span></th>
        {#each ["last", "min", "max", "mean"] as heading (heading)}
          <th scope="col" class="px-1.5 text-right font-normal">{heading}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each series as each, i (each.key)}
        {@const off = hidden.includes(each.key)}
        <tr class="transition-opacity {off ? 'opacity-40' : ''}">
          <th scope="row" class="text-left font-normal">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
              aria-pressed={!off}
              title="Click to hide or show. Ctrl or ⌘ click to show only this."
              onclick={(event) => toggle(event, each.key)}
            >
              <i class="inline-block h-[3px] w-2.5 rounded-full" style:background="var(--series-{each.color})"></i>{each.label}
            </button>
          </th>
          <td class="px-1.5 text-right">{show(stats[i].last)}</td>
          <td class="px-1.5 text-right">{show(stats[i].min)}</td>
          <td class="px-1.5 text-right">{show(stats[i].max)}</td>
          <td class="px-1.5 text-right">{show(stats[i].mean)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

{#if !fullscreen}
  <Dialog.Root bind:open={viewing}>
    <!-- Never taller than the screen, so its close button stays reachable on a landscape phone. -->
    <Dialog.Content class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-[min(72rem,calc(100vw-2rem))]">
      <Dialog.Title class="sr-only">{title}</Dialog.Title>
      {#if viewing}
        <TimeSeriesPanel
          {title}
          {unit}
          {format}
          {tick}
          {points}
          {series}
          {max}
          {dashboard}
          fullscreen
          height={Math.max(160, (innerHeight.current ?? 600) - 220)}
        />
      {/if}
    </Dialog.Content>
  </Dialog.Root>
{/if}
