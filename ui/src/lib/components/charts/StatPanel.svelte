<script lang="ts">
  import { linePath, yFor, type Point, type SeriesColor, type ThresholdState } from "$lib/chart";

  // A metric's newest value, large, with a faint trend of the range behind it. Always live: it ignores
  // Pause and zoom, so it never shows an old value as the current one.
  // - Above a threshold the tile turns amber or red, with the word beside the label, so colour is never alone.
  let {
    label,
    value,
    unit,
    format,
    trend,
    color,
    state = "ok",
  }: {
    label: string;
    value: number | null;
    unit: string;
    format: (value: number) => string;
    trend: (number | null)[];
    color: SeriesColor;
    state?: ThresholdState;
  } = $props();

  // One background class per state: Tailwind orders same-property utilities by name, not by class order.
  const LOOK: Record<ThresholdState, string> = {
    ok: "bg-card",
    warning: "border-status-warn bg-[color-mix(in_srgb,var(--status-warn)_8%,var(--card))]",
    critical: "border-status-bad bg-[color-mix(in_srgb,var(--status-bad)_8%,var(--card))]",
  };

  const WIDTH = 100;
  const HEIGHT = 40;

  const top = $derived(Math.max(0, ...trend.filter((each) => each !== null)) * 1.1 || 1);
  const coords = $derived(
    trend.map((each, i): Point =>
      each === null ? null : { x: trend.length > 1 ? (i * WIDTH) / (trend.length - 1) : WIDTH, y: yFor(each, top, HEIGHT) },
    ),
  );
  const line = $derived(linePath(coords));
  // The area under each unbroken run of readings.
  const area = $derived.by(() => {
    const parts: string[] = [];
    let run: { x: number; y: number }[] = [];
    const close = () => {
      if (run.length > 1) {
        const steps = run.map((point) => `L${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
        parts.push(`M${run[0].x.toFixed(1)} ${HEIGHT} ${steps} L${run[run.length - 1].x.toFixed(1)} ${HEIGHT} Z`);
      }
      run = [];
    };
    for (const point of coords) {
      if (point) run.push(point);
      else close();
    }
    close();
    return parts.join(" ");
  });
</script>

<div
  class="relative h-16 min-w-0 overflow-hidden rounded-lg border px-2.5 py-2 transition-colors max-md:h-[54px] max-md:px-2 max-md:py-1.5
         {LOOK[state]}"
>
  <svg
    class="pointer-events-none absolute inset-x-0 bottom-0 h-10 w-full"
    viewBox="0 0 {WIDTH} {HEIGHT}"
    preserveAspectRatio="none"
    style:color="var(--series-{color})"
    aria-hidden="true"
  >
    <path d={area} fill="currentColor" opacity="0.12" />
    <path
      d={line}
      fill="none"
      stroke="currentColor"
      stroke-opacity="0.5"
      stroke-width="1"
      stroke-linecap="round"
      stroke-linejoin="round"
      vector-effect="non-scaling-stroke"
    />
  </svg>
  <div class="relative flex items-center justify-between gap-1 text-[11px] text-muted-foreground">
    <span class="truncate">{label}</span>
    {#if state !== "ok"}
      <span class="inline-flex shrink-0 items-center gap-1 font-medium text-foreground">
        <span class="size-1.5 rounded-full {state === 'critical' ? 'bg-status-bad' : 'bg-status-warn'}" aria-hidden="true"></span>{state}
      </span>
    {/if}
  </div>
  <div class="relative truncate text-[22px] leading-tight font-semibold tabular-nums max-md:text-[17px]">
    {value === null ? "—" : format(value)}{#if unit && value !== null}<span
        class="ml-0.5 text-xs font-normal text-muted-foreground">{unit}</span
      >{/if}
  </div>
</div>
