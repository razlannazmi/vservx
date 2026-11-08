<script lang="ts">
  import type { UsagePointRead } from "$lib/api/client";
  import { linePath, niceMax, yFor, type Point } from "$lib/chart";
  import { clockTime } from "$lib/format";
  import { HISTORY_MINUTES } from "$lib/watch";

  type Pick = (point: UsagePointRead) => number | null;

  // One series (or two, the second dashed and lighter) over the last HISTORY_MINUTES, in the text colour.
  // Its section says "last N min", so the chart only labels its top value.
  let {
    title,
    points,
    value,
    second,
    legend,
    format,
    max,
  }: {
    title: string;
    points: UsagePointRead[];
    value: Pick;
    second?: Pick;
    legend?: [string, string?];
    format: (value: number) => string;
    max?: number;
  } = $props();

  const WIDTH = 300;
  const HEIGHT = 78;
  const WINDOW_MS = HISTORY_MINUTES * 60_000;

  // The newest reading sits at the right edge ("now"); points are placed by time, so gaps show.
  const end = $derived(points.length > 0 ? Date.parse(points[points.length - 1].at) : Date.now());
  const top = $derived(
    max ??
      niceMax(
        Math.max(
          0,
          ...points.flatMap((point) => [value(point), second?.(point) ?? null]).filter((each) => each !== null),
        ),
      ),
  );
  const main = $derived(line(value));
  const dashed = $derived(second ? line(second) : "");

  let hover = $state<UsagePointRead | null>(null);
  const hoverX = $derived(hover ? xOf(hover.at) : 0);

  function xOf(at: string): number {
    return ((Date.parse(at) - (end - WINDOW_MS)) / WINDOW_MS) * WIDTH;
  }

  function line(pick: Pick): string {
    return linePath(
      points.map((point): Point => {
        const each = pick(point);
        return each === null ? null : { x: xOf(point.at), y: yFor(each, top, HEIGHT) };
      }),
    );
  }

  function shown(each: number | null): string {
    return each === null ? "—" : format(each);
  }

  function label(point: UsagePointRead): string {
    if (!second) return `${clockTime(point.at)} · ${shown(value(point))}`;
    const [first, other] = legend ?? ["", ""];
    return `${clockTime(point.at)} · ${first} ${shown(value(point))} · ${other ?? ""} ${shown(second(point))}`;
  }

  // The reading nearest the pointer.
  function track(event: PointerEvent) {
    if (points.length === 0) return;
    const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const at = end - WINDOW_MS + ((event.clientX - box.left) / box.width) * WINDOW_MS;
    let nearest = points[0];
    for (const point of points) {
      if (Math.abs(Date.parse(point.at) - at) < Math.abs(Date.parse(nearest.at) - at)) nearest = point;
    }
    hover = nearest;
  }
</script>

<figure class="min-w-0">
  <figcaption class="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
    <span>{title}</span>
    {#if legend}
      <span class="flex gap-2.5">
        <span class="inline-flex items-center gap-1"><i class="inline-block w-3 border-t-[1.5px] border-foreground"></i>{legend[0]}</span>
        {#if legend[1]}
          <span class="inline-flex items-center gap-1">
            <i class="inline-block w-3 border-t-[1.5px] border-dashed border-foreground opacity-55"></i>{legend[1]}
          </span>
        {/if}
      </span>
    {/if}
  </figcaption>
  <!-- A tap shows the reading there too, and keeps it until the next tap; a sideways drag follows the
       finger while an up-down one still scrolls the page. -->
  <div
    class="relative mt-1 touch-pan-y text-foreground"
    role="img"
    aria-label="{title}, last {HISTORY_MINUTES} minutes"
    onpointerdown={track}
    onpointermove={track}
    onpointerleave={(event) => {
      if (event.pointerType === "mouse") hover = null;
    }}
    onpointercancel={() => (hover = null)}
  >
    <svg class="block h-[78px] w-full" viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="none" aria-hidden="true">
      {#each [0.25, 0.5, 0.75] as share (share)}
        <line
          x1="0"
          x2={WIDTH}
          y1={HEIGHT * share}
          y2={HEIGHT * share}
          stroke="var(--border)"
          stroke-width="1"
          vector-effect="non-scaling-stroke"
        />
      {/each}
      {#if dashed}
        <path
          d={dashed}
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-dasharray="4 3"
          stroke-linecap="round"
          opacity="0.55"
          vector-effect="non-scaling-stroke"
        />
      {/if}
      <path
        d={main}
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
        vector-effect="non-scaling-stroke"
      />
      {#if hover}
        <line
          x1={hoverX}
          x2={hoverX}
          y1="0"
          y2={HEIGHT}
          stroke="currentColor"
          stroke-opacity="0.35"
          stroke-width="1"
          vector-effect="non-scaling-stroke"
        />
      {/if}
    </svg>
    {#if hover}
      {@const share = Math.min(Math.max(hoverX / WIDTH, 0), 1) * 100}
      <div
        class="pointer-events-none absolute top-0 rounded border bg-popover px-1.5 py-0.5 text-[11px] whitespace-nowrap text-popover-foreground tabular-nums shadow-sm"
        style:left="{share}%"
        style:transform="translateX(-{share}%)"
      >
        {label(hover)}
      </div>
    {/if}
  </div>
  <div class="text-right text-[10px] text-muted-foreground tabular-nums">max {format(top)}</div>
</figure>
