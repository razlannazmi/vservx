<script lang="ts">
  import { untrack } from "svelte";
  import type { ServerRead, WatchSummaryRead } from "$lib/api/client";
  import { FLASH_HOLD_MS } from "$lib/motion";
  import { followLink } from "$lib/router.svelte";
  import { TONE_DOT, TONE_FLASH, type Tone } from "$lib/servers";
  import { cardStatus } from "$lib/watch";

  let {
    server,
    href,
    selected,
    summary,
  }: { server: ServerRead; href: string; selected: boolean; summary?: WatchSummaryRead } = $props();

  const status = $derived(cardStatus(server, summary));

  // A change of colour after the first watch summary tints the card for a moment, so it's noticed.
  let flashing = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  // Not reactive: the tone last shown from watching; null until the first summary, so loading never flashes.
  let shown: Tone | null = null;

  $effect(() => {
    const tone = status.tone;
    const watched = summary !== undefined;
    untrack(() => {
      if (!watched) return;
      if (shown !== null && shown !== tone) {
        clearTimeout(timer);
        flashing = true;
        timer = setTimeout(() => (flashing = false), FLASH_HOLD_MS);
      }
      shown = tone;
    });
  });

  $effect(() => () => clearTimeout(timer));
</script>

<!-- The selected card is outlined in the text colour; hover lifts it a pixel (not under reduced motion). -->
<a
  {href}
  onclick={followLink}
  aria-current={selected ? "page" : undefined}
  class="relative isolate block rounded-lg border bg-card px-3 py-2 text-sm outline-none transition-[translate,box-shadow,border-color] duration-200
         before:pointer-events-none before:absolute before:inset-0 before:-z-10 before:rounded-[inherit]
         {TONE_FLASH[status.tone]}
         {flashing ? 'before:opacity-100' : 'before:opacity-0 before:transition-opacity before:duration-250 before:ease-out'}
         hover:shadow-sm focus-visible:ring-2 focus-visible:ring-ring motion-safe:hover:-translate-y-px
         {selected ? 'border-foreground ring-1 ring-foreground' : ''}"
>
  <span class="flex items-center gap-2 font-medium">
    <span class="size-2 shrink-0 rounded-full {TONE_DOT[status.tone]}" aria-hidden="true"></span>
    <span class="truncate">{server.name}</span>
  </span>
  <span class="mt-0.5 block truncate text-xs text-muted-foreground" title={status.label}>{status.label}</span>
</a>
