<script lang="ts">
  import { untrack } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import type { InstanceState, WatchedInstanceRead } from "$lib/api/client";
  import Sparkline from "$lib/components/Sparkline.svelte";
  import { Input } from "$lib/components/ui/input/index.js";
  import { FLASH_HOLD_MS } from "$lib/motion";
  import { followLink } from "$lib/router.svelte";
  import { TONE_DOT, TONE_FLASH } from "$lib/servers";
  import {
    changedStates,
    formatNumber,
    formatSeconds,
    gpuLabel,
    HISTORY_MINUTES,
    INSTANCE_FILTER_FROM,
    INSTANCE_FILTERS,
    INSTANCE_TONE,
    INSTANCE_WORDS,
    matchesFilter,
    matchesQuery,
    shortModel,
    type InstanceFilter,
  } from "$lib/watch";

  // One row per container, in the order given (by name), each a link to that instance.
  // Stopped ones fold away, long lists get a search and state chips, and the rows scroll inside a capped height.
  let {
    instances,
    selected,
    hrefFor,
    onpick,
  }: {
    instances: WatchedInstanceRead[];
    selected: string | null;
    hrefFor: (name: string) => string;
    onpick?: (name: string) => void;
  } = $props();

  let query = $state("");
  let filter = $state<InstanceFilter>("all");
  // Stopped ones stay folded until someone unfolds them, unless the open one is stopped or nothing else runs.
  let stoppedChosen = $state<boolean | null>(null);
  let scroller = $state<HTMLDivElement | null>(null);
  let header = $state<HTMLDivElement | null>(null);

  const filterable = $derived(instances.length >= INSTANCE_FILTER_FROM);
  // The search and chips only count while they're on screen.
  const activeQuery = $derived(filterable ? query.trim() : "");
  const activeFilter = $derived<InstanceFilter>(filterable ? filter : "all");
  const counts = $derived(
    Object.fromEntries(
      INSTANCE_FILTERS.map(([value]) => [value, instances.filter((each) => matchesFilter(each, value)).length]),
    ) as Record<InstanceFilter, number>,
  );
  const showStopped = $derived(
    stoppedChosen ??
      (instances.find((each) => each.name === selected)?.state === "stopped" || counts.stopped === instances.length),
  );
  // Searching or picking a chip looks through the stopped ones too, so the fold only applies to the plain list.
  const folding = $derived(activeFilter === "all" && activeQuery === "");
  const rows = $derived(
    instances.filter(
      (each) =>
        matchesFilter(each, activeFilter) &&
        matchesQuery(each, activeQuery) &&
        (!folding || showStopped || each.state !== "stopped"),
    ),
  );

  const cell = "px-2 py-2 whitespace-nowrap";
  const number = `${cell} text-right font-mono tabular-nums`;

  // Keep the open instance's row in view when it changes (an address can name one far down the list).
  // The elements are tracked too: bind:this fills them in after the first run.
  $effect(() => {
    const box = scroller;
    const top = header;
    if (selected === null || !box) return;
    untrack(() => {
      const row = box.querySelector<HTMLElement>('[aria-current="true"]');
      if (!row) return;
      const above = row.offsetTop - (top?.offsetHeight ?? 0);
      const below = row.offsetTop + row.offsetHeight;
      if (above < box.scrollTop) box.scrollTop = above;
      else if (below > box.scrollTop + box.clientHeight) box.scrollTop = below - box.clientHeight;
    });
  });

  // Rows whose state changed since the last poll stay tinted for a moment, then fade, so live changes are seen.
  const flashing = new SvelteSet<string>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  // Not reactive: each instance's state at the last poll, to compare the next one with.
  let lastStates = new Map<string, InstanceState>();

  $effect(() => {
    const list = instances;
    untrack(() => {
      for (const name of changedStates(lastStates, list)) {
        clearTimeout(timers.get(name));
        flashing.add(name);
        timers.set(
          name,
          setTimeout(() => {
            flashing.delete(name);
            timers.delete(name);
          }, FLASH_HOLD_MS),
        );
      }
      lastStates = new Map(list.map((each) => [each.name, each.state]));
    });
  });

  $effect(() => () => timers.forEach((timer) => clearTimeout(timer)));

  function clearFilters() {
    query = "";
    filter = "all";
  }

  // Only a click the app handled itself (not one opening a new tab) counts as picking the row.
  function pick(event: MouseEvent, name: string) {
    followLink(event);
    if (event.defaultPrevented) onpick?.(name);
  }
</script>

{#if filterable}
  <div class="mb-2 flex flex-wrap items-center gap-2">
    <Input
      type="search"
      bind:value={query}
      placeholder="Search name, model or port"
      aria-label="Search instances"
      autocomplete="off"
      class="h-7 w-full text-xs sm:w-60 md:text-xs"
    />
    <div class="flex flex-wrap gap-1" role="group" aria-label="Show instances">
      {#each INSTANCE_FILTERS as [value, label] (value)}
        {@const on = filter === value}
        <button
          type="button"
          aria-pressed={on}
          onclick={() => (filter = value)}
          class="inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs outline-none transition-colors duration-150
                 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring
                 {on ? 'border-foreground/40 bg-muted font-medium text-foreground' : 'text-muted-foreground'}"
        >
          {#if value === "attention" && counts.attention > 0}
            <span class="size-1.5 shrink-0 rounded-full {TONE_DOT.bad}" aria-hidden="true"></span>
          {/if}
          {label}
          <span class="font-mono tabular-nums {counts[value] === 0 ? 'opacity-50' : ''}">{counts[value]}</span>
        </button>
      {/each}
    </div>
  </div>
{/if}

<!-- Rows are links, so the table is a grid: each row spans it as a subgrid. About eight rows show; the rest scroll under a sticky header.
     All ten columns need about 50rem without wrapping; narrower than that, the trend column goes (the open instance's charts are below). -->
<div bind:this={scroller} class="relative max-h-[19.5rem] overflow-auto">
  <!-- The query box sits inside the scroller so its width leaves out the scrollbar. -->
  <div class="@container">
    <div
      class="grid min-w-[45rem] grid-cols-[auto_minmax(7rem,1fr)_minmax(7rem,1.5fr)_auto_auto_auto_auto_auto_auto] text-xs
             @min-[50rem]:grid-cols-[auto_minmax(7rem,1fr)_minmax(7rem,1.5fr)_auto_auto_auto_auto_auto_auto_auto]"
    >
      <div
        bind:this={header}
        class="sticky top-0 z-10 col-span-full grid grid-cols-subgrid border-b bg-background font-medium text-muted-foreground"
        aria-hidden="true"
      >
        <span class="px-2 py-1.5">State</span>
        <span class="px-2 py-1.5">Container</span>
        <span class="px-2 py-1.5">Model</span>
        <span class="px-2 py-1.5">Port</span>
        <span class="px-2 py-1.5">GPU</span>
        <span class="hidden px-2 py-1.5 @min-[50rem]:block">Last {HISTORY_MINUTES} min</span>
        <span class="px-2 py-1.5 text-right">Run · wait</span>
        <span class="px-2 py-1.5 text-right">KV cache</span>
        <span class="px-2 py-1.5 text-right">Tok/s out</span>
        <span class="px-2 py-1.5 text-right">First token</span>
      </div>
      {#each rows as instance (instance.name)}
        {@const usage = instance.state === "ready" ? instance.usage : null}
        {@const current = instance.name === selected}
        <a
          href={hrefFor(instance.name)}
          onclick={(event) => pick(event, instance.name)}
          aria-current={current ? "true" : undefined}
          class="relative isolate col-span-full grid grid-cols-subgrid items-center border-b outline-none
                 before:pointer-events-none before:absolute before:inset-0 before:-z-10
                 {TONE_FLASH[INSTANCE_TONE[instance.state]]}
                 {flashing.has(instance.name) ? 'before:opacity-100' : 'before:opacity-0 before:transition-opacity before:duration-250 before:ease-out'}
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
          <span class="{cell} hidden @min-[50rem]:block">
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
  {#if rows.length === 0}
    <p class="px-2 py-6 text-center text-xs text-muted-foreground">
      No containers match ·
      <button
        type="button"
        class="rounded-sm underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        onclick={clearFilters}
      >
        show all
      </button>
    </p>
  {/if}
</div>

{#if folding && counts.stopped > 0 && counts.stopped < instances.length}
  <button
    type="button"
    class="mt-2 rounded-sm text-xs text-muted-foreground underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
    aria-expanded={showStopped}
    onclick={() => (stoppedChosen = !showStopped)}
  >
    {showStopped ? "Hide stopped" : `Show ${counts.stopped} stopped`}
  </button>
{/if}
