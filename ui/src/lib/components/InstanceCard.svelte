<script lang="ts">
  import HistoryIcon from "@lucide/svelte/icons/history";
  import { TONE_DOT, TONE_FLASH } from "$lib/servers";
  import { changedLabel } from "$lib/snapshots";
  import {
    dayMonth,
    formatNumber,
    formatSeconds,
    gpuLabel,
    INSTANCE_TONE,
    INSTANCE_WORDS,
    shortModel,
    type InstanceRow,
  } from "$lib/watch";

  // Phones only: one instance as a card, what a table row says stacked so nothing needs a sideways swipe.
  // State first, then what it serves, then the live numbers for ready ones.
  let {
    row,
    current,
    flashing,
    href,
    onpick,
    onsnapshots,
  }: {
    row: InstanceRow;
    current: boolean;
    flashing: boolean;
    href: string;
    onpick: (event: MouseEvent) => void;
    onsnapshots: () => void;
  } = $props();

  const card = $derived(
    `relative isolate block rounded-lg border bg-card px-3 py-2 pr-10 text-xs outline-none
     before:pointer-events-none before:absolute before:inset-0 before:-z-10 before:rounded-[inherit]
     hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring
     ${current ? "border-foreground ring-1 ring-foreground" : ""}`,
  );
</script>

{#snippet number(label: string, value: string)}
  <span class="min-w-0">
    <span class="block text-[10px] text-muted-foreground">{label}</span>
    <span class="block truncate font-mono tabular-nums">{value}</span>
  </span>
{/snippet}

<li class="relative">
  {#if row.removed}
    {@const gone = row.instance}
    <a {href} onclick={onpick} aria-current={current ? "true" : undefined} class="{card} text-muted-foreground">
      <span class="flex min-w-0 items-center gap-1.5">
        <span class="size-2 shrink-0 rounded-full {TONE_DOT.none}" aria-hidden="true"></span>
        <span class="shrink-0">Removed · {dayMonth(gone.removed_at)}</span>
        <span class="truncate font-mono font-semibold opacity-70">{gone.name}</span>
      </span>
      <span class="mt-0.5 block truncate pl-3.5 font-mono opacity-70" title={gone.model ?? undefined}>{shortModel(gone.model)}</span>
    </a>
  {:else}
    {@const instance = row.instance}
    {@const usage = instance.state === "ready" ? instance.usage : null}
    {@const tag = changedLabel(instance.changed_at)}
    {@const gpu = gpuLabel(instance.gpus)}
    <a
      {href}
      onclick={onpick}
      aria-current={current ? "true" : undefined}
      class="{card} {TONE_FLASH[INSTANCE_TONE[instance.state]]}
             {flashing ? 'before:opacity-100' : 'before:opacity-0 before:transition-opacity before:duration-250 before:ease-out'}"
    >
      <span class="flex min-w-0 items-center gap-1.5">
        <span
          class="size-2 shrink-0 rounded-full {TONE_DOT[INSTANCE_TONE[instance.state]]}
                 {instance.state === 'starting' ? 'motion-safe:animate-pulse' : ''}"
          aria-hidden="true"
        ></span>
        <span class="shrink-0">{INSTANCE_WORDS[instance.state]} ·</span>
        <span class="truncate font-mono font-semibold">{instance.name}</span>
        {#if tag}
          <span class="shrink-0 rounded-sm border border-status-warn px-1 text-[0.625rem] leading-4 text-status-warn">{tag}</span>
        {/if}
      </span>
      <span class="mt-0.5 block truncate pl-3.5 font-mono text-muted-foreground" title={instance.model ?? undefined}>
        {shortModel(instance.model)} · :{instance.port}{gpu === "—" ? "" : ` · GPU ${gpu}`}
      </span>
      {#if usage}
        <span class="mt-1.5 grid grid-cols-4 gap-2 pl-3.5">
          {@render number("Run · wait", `${formatNumber(usage.running)} · ${formatNumber(usage.waiting)}`)}
          {@render number("KV cache", usage.kv_cache_percent === null ? "—" : `${formatNumber(usage.kv_cache_percent)}%`)}
          {@render number("Tok/s out", formatNumber(usage.tokens_out_per_s))}
          {@render number("First token", formatSeconds(usage.ttft_seconds))}
        </span>
      {/if}
    </a>
  {/if}
  <!-- A sibling of the card's link, never inside it: a button can't sit in a link. -->
  <button
    type="button"
    aria-label={`Snapshots of ${row.instance.name}`}
    title={`Snapshots of ${row.instance.name}`}
    onclick={onsnapshots}
    class="absolute top-1.5 right-1.5 inline-flex size-7 items-center justify-center rounded-md text-muted-foreground outline-none
           hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
  >
    <HistoryIcon class="size-3.5" aria-hidden="true" />
  </button>
</li>
