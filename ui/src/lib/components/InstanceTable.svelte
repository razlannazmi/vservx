<script lang="ts">
  import HistoryIcon from "@lucide/svelte/icons/history";
  import { untrack } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import type { InstanceState, RemovedInstanceRead, WatchedInstanceRead } from "$lib/api/client";
  import InstanceCard from "$lib/components/InstanceCard.svelte";
  import Sparkline from "$lib/components/Sparkline.svelte";
  import { Input } from "$lib/components/ui/input/index.js";
  import { phone } from "$lib/layout.svelte";
  import { FLASH_HOLD_MS } from "$lib/motion";
  import { followLink } from "$lib/router.svelte";
  import { TONE_DOT, TONE_FLASH } from "$lib/servers";
  import { changedLabel } from "$lib/snapshots";
  import {
    changedStates,
    dayMonth,
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
    type InstanceRow,
  } from "$lib/watch";

  // One row per container, in the order given (by name), each a link to that instance.
  // Stopped ones fold away, long lists get a search and state chips, and the rows scroll inside a capped height.
  // Containers removed in the last 7 days stay as greyed rows, folded and filtered like stopped ones.
  let {
    instances,
    removed = [],
    selected,
    hrefFor,
    onpick,
    onsnapshots,
  }: {
    instances: WatchedInstanceRead[];
    removed?: RemovedInstanceRead[];
    selected: string | null;
    hrefFor: (name: string) => string;
    onpick?: (name: string) => void;
    onsnapshots: (name: string) => void;
  } = $props();

  let query = $state("");
  let filter = $state<InstanceFilter>("all");
  // Stopped ones stay folded until someone unfolds them, unless the open one is stopped or nothing else runs.
  let stoppedChosen = $state<boolean | null>(null);
  let scroller = $state<HTMLDivElement | null>(null);
  let header = $state<HTMLDivElement | null>(null);

  const total = $derived(instances.length + removed.length);
  const filterable = $derived(total >= INSTANCE_FILTER_FROM);
  // The search and chips only count while they're on screen.
  const activeQuery = $derived(filterable ? query.trim() : "");
  const activeFilter = $derived<InstanceFilter>(filterable ? filter : "all");
  // Removed rows count with stopped ones (and all).
  const counts = $derived(
    Object.fromEntries(
      INSTANCE_FILTERS.map(([value]) => [
        value,
        instances.filter((each) => matchesFilter(each, value)).length +
          (value === "all" || value === "stopped" ? removed.length : 0),
      ]),
    ) as Record<InstanceFilter, number>,
  );
  const showStopped = $derived(
    stoppedChosen ??
      (instances.find((each) => each.name === selected)?.state === "stopped" ||
        removed.some((each) => each.name === selected) ||
        counts.stopped === total),
  );
  // Searching or picking a chip looks through the stopped ones too, so the fold only applies to the plain list.
  const folding = $derived(activeFilter === "all" && activeQuery === "");
  const rows = $derived(
    [
      ...instances
        .filter(
          (each) =>
            matchesFilter(each, activeFilter) &&
            matchesQuery(each, activeQuery) &&
            (!folding || showStopped || each.state !== "stopped"),
        )
        .map((instance): InstanceRow => ({ removed: false, instance })),
      ...removed
        .filter(
          (each) =>
            (activeFilter === "all" || activeFilter === "stopped") &&
            matchesRemoved(each, activeQuery) &&
            (!folding || showStopped),
        )
        .map((instance): InstanceRow => ({ removed: true, instance })),
    ].sort((a, b) => (a.instance.name < b.instance.name ? -1 : a.instance.name > b.instance.name ? 1 : 0)),
  );

  // A removed container has no port: it's found by name or model.
  function matchesRemoved(each: RemovedInstanceRead, words: string): boolean {
    const text = `${each.name} ${each.model ?? ""}`.toLowerCase();
    return words.toLowerCase().split(/\s+/).filter(Boolean).every((word) => text.includes(word));
  }

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

{#snippet noMatch()}
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
{/snippet}

<!-- On a phone, one card per instance: the page scrolls, not a box inside it, and nothing hides off to the side. -->
{#if phone.current}
  <ul class="space-y-1.5" aria-label="Instances">
    {#each rows as row (row.instance.name)}
      {@const name = row.instance.name}
      <InstanceCard
        {row}
        current={name === selected}
        flashing={flashing.has(name)}
        href={hrefFor(name)}
        onpick={(event) => pick(event, name)}
        onsnapshots={() => onsnapshots(name)}
      />
    {/each}
  </ul>
  {#if rows.length === 0}{@render noMatch()}{/if}
{:else}
<!-- Rows are links, so the table is a grid: each row spans it as a subgrid. About eight rows show; the rest scroll under a sticky header.
     All ten columns need about 50rem without wrapping; narrower than that, the trend column goes (the open instance's charts are below). -->
<div bind:this={scroller} class="relative max-h-[19.5rem] overflow-auto">
  <!-- The query box sits inside the scroller so its width leaves out the scrollbar. -->
  <div class="@container">
    <div
      class="grid min-w-[45rem] grid-cols-[auto_minmax(7rem,1fr)_minmax(7rem,1.5fr)_auto_minmax(4rem,10rem)_auto_auto_auto_auto_auto] text-xs
             @min-[50rem]:grid-cols-[auto_minmax(7rem,1fr)_minmax(7rem,1.5fr)_auto_minmax(4rem,10rem)_auto_auto_auto_auto_auto_auto]"
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
        <span></span>
      </div>
      {#each rows as row (row.instance.name)}
        {@const current = row.instance.name === selected}
        {#if row.removed}
          {@const gone = row.instance}
          <a
            href={hrefFor(gone.name)}
            onclick={(event) => pick(event, gone.name)}
            aria-current={current ? "true" : undefined}
            class="col-[1/-2] grid grid-cols-subgrid items-center border-b text-muted-foreground outline-none
                   hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset
                   {current ? 'bg-muted shadow-[inset_2px_0_0_var(--foreground)]' : ''}"
          >
            <span class="{cell} flex items-center gap-1.5">
              <span class="size-2 shrink-0 rounded-full {TONE_DOT.none}" aria-hidden="true"></span>
              Removed · {dayMonth(gone.removed_at)}
            </span>
            <span class="{cell} truncate font-mono font-semibold opacity-70">{gone.name}</span>
            <span class="{cell} truncate font-mono opacity-70" title={gone.model ?? undefined}>{shortModel(gone.model)}</span>
            <span class={cell}>—</span>
            <span class={cell}>—</span>
            <span class="{cell} hidden @min-[50rem]:block">—</span>
            {#each { length: 4 }, i (i)}
              <span class={number}>—</span>
            {/each}
          </a>
        {:else}
        {@const instance = row.instance}
        {@const usage = instance.state === "ready" ? instance.usage : null}
        {@const tag = changedLabel(instance.changed_at)}
        <a
          href={hrefFor(instance.name)}
          onclick={(event) => pick(event, instance.name)}
          aria-current={current ? "true" : undefined}
          class="relative isolate col-[1/-2] grid grid-cols-subgrid items-center border-b outline-none
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
          <span class="{cell} flex min-w-0 items-center gap-1.5">
            <span class="truncate font-mono font-semibold">{instance.name}</span>
            {#if tag}
              <span class="shrink-0 rounded-sm border border-status-warn px-1 text-[0.625rem] leading-4 text-status-warn">{tag}</span>
            {/if}
          </span>
          <span class="{cell} truncate font-mono" title={instance.model ?? undefined}>{shortModel(instance.model)}</span>
          <span class="{cell} font-mono tabular-nums">{instance.port}</span>
          <span class="{cell} truncate font-mono tabular-nums" title={instance.gpus?.join(", ") || undefined}>{gpuLabel(instance.gpus)}</span>
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
        {/if}
        <!-- A sibling of the row's link, never inside it: a button can't sit in a link. -->
        <span class="col-[-2/-1] flex h-full items-center border-b px-1 {current ? 'bg-muted' : ''}">
          <button
            type="button"
            aria-label={`Snapshots of ${row.instance.name}`}
            title={`Snapshots of ${row.instance.name}`}
            onclick={() => onsnapshots(row.instance.name)}
            class="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground outline-none
                   hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <HistoryIcon class="size-3.5" aria-hidden="true" />
          </button>
        </span>
      {/each}
    </div>
  </div>
  {#if rows.length === 0}{@render noMatch()}{/if}
</div>
{/if}

{#if folding && counts.stopped > 0 && counts.stopped < total}
  <button
    type="button"
    class="mt-2 rounded-sm text-xs text-muted-foreground underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
    aria-expanded={showStopped}
    onclick={() => (stoppedChosen = !showStopped)}
  >
    {showStopped ? "Hide stopped" : `Show ${counts.stopped} stopped`}
  </button>
{/if}
