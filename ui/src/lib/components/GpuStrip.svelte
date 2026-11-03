<script lang="ts">
  import type { GpuRead } from "$lib/api/client";
  import { formatNumber } from "$lib/watch";

  // One tile per GPU: utilisation as a number and a bar, memory, temperature, and who uses it.
  let { gpus }: { gpus: GpuRead[] } = $props();

  const gb = (mib: number | null) => formatNumber(mib === null ? null : mib / 1024, 1);
</script>

<ul class="grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-2">
  {#each gpus as gpu (gpu.index)}
    <li class="flex min-w-0 flex-col gap-1 rounded-md border px-2.5 py-2 text-xs">
      <div class="flex items-baseline justify-between gap-2">
        <span class="font-semibold">GPU {gpu.index}</span>
        <span class="tabular-nums">{gpu.utilization_percent === null ? "—" : `${formatNumber(gpu.utilization_percent)}%`}</span>
      </div>
      <div class="h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div class="h-full bg-foreground" style:width="{Math.min(Math.max(gpu.utilization_percent ?? 0, 0), 100)}%"></div>
      </div>
      <div class="text-muted-foreground tabular-nums">
        {gb(gpu.memory_used_mib)} / {gb(gpu.memory_total_mib)} GB · {gpu.temperature_c === null ? "—" : `${formatNumber(gpu.temperature_c)}°`}
      </div>
      <div class="truncate font-mono text-[11px] text-muted-foreground" title={gpu.instances.join(", ") || undefined}>
        {gpu.instances.length > 0 ? gpu.instances.join(", ") : "free"}
      </div>
    </li>
  {/each}
</ul>
