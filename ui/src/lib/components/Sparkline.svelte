<script lang="ts">
  import { linePath, yFor } from "$lib/chart";

  // A small trend line, oldest first, in the text colour; gaps where a reading is missing.
  let { values, max }: { values: (number | null)[]; max?: number } = $props();

  const WIDTH = 72;
  const HEIGHT = 16;

  const top = $derived(max ?? Math.max(1, ...values.map((each) => each ?? 0)));
  const d = $derived(
    linePath(
      values.map((value, i) =>
        value === null
          ? null
          : { x: values.length > 1 ? (i * WIDTH) / (values.length - 1) : WIDTH, y: yFor(value, top, HEIGHT) },
      ),
    ),
  );
</script>

<svg class="block h-4 w-18" viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="none" aria-hidden="true">
  <path
    {d}
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    vector-effect="non-scaling-stroke"
  />
</svg>
