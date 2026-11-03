<script lang="ts">
  import type { WatchedInstanceRead } from "$lib/api/client";
  import Sparkline from "$lib/components/Sparkline.svelte";
  import { followLink } from "$lib/router.svelte";
  import { TONE_DOT } from "$lib/servers";
  import { formatNumber, formatSeconds, gpuLabel, INSTANCE_TONE, INSTANCE_WORDS, shortModel } from "$lib/watch";

  // One row per container, in the order given (by name), each a link to that instance.
  let {
    instances,
    selected,
    hrefFor,
  }: { instances: WatchedInstanceRead[]; selected: string | null; hrefFor: (name: string) => string } = $props();

  const cell = "px-2 py-2 whitespace-nowrap";
  const number = `${cell} text-right font-mono tabular-nums`;
</script>

<!-- Rows are links, so the table is a grid: each row spans it as a subgrid. -->
<div class="overflow-x-auto">
  <div
    class="grid min-w-[48rem] grid-cols-[auto_minmax(7rem,1fr)_minmax(7rem,1.5fr)_auto_auto_auto_auto_auto_auto_auto] text-xs"
  >
    <div class="col-span-full grid grid-cols-subgrid border-b font-medium text-muted-foreground" aria-hidden="true">
      <span class="px-2 py-1.5">State</span>
      <span class="px-2 py-1.5">Container</span>
      <span class="px-2 py-1.5">Model</span>
      <span class="px-2 py-1.5">Port</span>
      <span class="px-2 py-1.5">GPU</span>
      <span class="px-2 py-1.5">Last 15 min</span>
      <span class="px-2 py-1.5 text-right">Run · wait</span>
      <span class="px-2 py-1.5 text-right">KV cache</span>
      <span class="px-2 py-1.5 text-right">Tok/s out</span>
      <span class="px-2 py-1.5 text-right">First token</span>
    </div>
    {#each instances as instance (instance.name)}
      {@const usage = instance.state === "ready" ? instance.usage : null}
      {@const current = instance.name === selected}
      <a
        href={hrefFor(instance.name)}
        onclick={followLink}
        aria-current={current ? "true" : undefined}
        class="col-span-full grid grid-cols-subgrid items-center border-b outline-none transition-colors duration-150
               hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset
               {current ? 'bg-muted shadow-[inset_2px_0_0_var(--foreground)]' : ''}"
      >
        <span class="{cell} flex items-center gap-1.5">
          <span
            class="size-2 shrink-0 rounded-full {TONE_DOT[INSTANCE_TONE[instance.state]]}
                   {instance.state === 'starting' ? 'motion-safe:animate-pulse' : ''}"
            aria-hidden="true"
          ></span>
          {INSTANCE_WORDS[instance.state]}
        </span>
        <span class="{cell} truncate font-mono font-semibold">{instance.name}</span>
        <span class="{cell} truncate font-mono" title={instance.model ?? undefined}>{shortModel(instance.model)}</span>
        <span class="{cell} font-mono tabular-nums">{instance.port}</span>
        <span class="{cell} font-mono tabular-nums">{gpuLabel(instance.gpus)}</span>
        <span class={cell}>
          {#if usage}
            <Sparkline values={instance.running_trend} />
          {:else}
            <span class="text-muted-foreground">—</span>
          {/if}
        </span>
        {#if usage}
          <span class={number}>{formatNumber(usage.running)} · {formatNumber(usage.waiting)}</span>
          <span class={number}>{usage.kv_cache_percent === null ? "—" : `${formatNumber(usage.kv_cache_percent)}%`}</span>
          <span class={number}>{formatNumber(usage.tokens_out_per_s)}</span>
          <span class={number}>{formatSeconds(usage.ttft_seconds)}</span>
        {:else}
          {#each { length: 4 }, i (i)}
            <span class="{number} text-muted-foreground">—</span>
          {/each}
        {/if}
      </a>
    {/each}
  </div>
</div>
