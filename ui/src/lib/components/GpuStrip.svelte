<script lang="ts">
  import type { GpuRead } from "$lib/api/client";
  import { formatNumber, gpuMemoryPercent } from "$lib/watch";

  // One tile per GPU: memory and compute each as a number and a bar, temperature, and who uses it.
  // vLLM reserves most of a GPU's memory up front, so memory is the bar that says a GPU is taken.
  let { gpus }: { gpus: GpuRead[] } = $props();

  const gb = (mib: number | null) => formatNumber(mib === null ? null : mib / 1024, 1);
  const clamp = (percent: number | null) => Math.min(Math.max(percent ?? 0, 0), 100);
</script>

<ul class="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
  {#each gpus as gpu (gpu.index)}
    {@const memory = gpuMemoryPercent(gpu)}
    <li class="flex min-w-0 flex-col gap-1.5 rounded-md border px-2.5 py-2 text-xs">
      <div class="flex items-baseline justify-between gap-2">
        <span class="font-semibold">GPU {gpu.index}</span>
        <span class="text-muted-foreground tabular-nums">{gpu.temperature_c === null ? "—" : `${formatNumber(gpu.temperature_c)}°C`}</span>
      </div>
      <div class="space-y-0.5" title={memory === null ? undefined : `Memory ${formatNumber(memory)}% used`}>
        <div class="flex items-baseline justify-between gap-2">
          <span class="text-muted-foreground">Memory</span>
          <span class="tabular-nums">{gb(gpu.memory_used_mib)} / {gb(gpu.memory_total_mib)} GB</span>
        </div>
        <div class="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div
            class="h-full origin-left bg-foreground transition-transform duration-250 ease-in-out"
            style:transform="scaleX({clamp(memory) / 100})"
          ></div>
        </div>
      </div>
      <div class="space-y-0.5">
        <div class="flex items-baseline justify-between gap-2">
          <span class="text-muted-foreground">Compute</span>
          <span class="tabular-nums">{gpu.utilization_percent === null ? "—" : `${formatNumber(gpu.utilization_percent)}%`}</span>
        </div>
        <div class="h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div
            class="h-full origin-left bg-muted-foreground transition-transform duration-250 ease-in-out"
            style:transform="scaleX({clamp(gpu.utilization_percent) / 100})"
          ></div>
        </div>
      </div>
      <div class="truncate font-mono text-[11px] text-muted-foreground" title={gpu.instances.join(", ") || undefined}>
        {gpu.instances.length > 0 ? gpu.instances.join(", ") : "free"}
      </div>
    </li>
  {/each}
</ul>
