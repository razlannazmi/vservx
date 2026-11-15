<script lang="ts">
  import PauseIcon from "@lucide/svelte/icons/pause";
  import PlayIcon from "@lucide/svelte/icons/play";
  import ZoomOutIcon from "@lucide/svelte/icons/zoom-out";
  import { tick } from "svelte";
  import type { Dashboard } from "$lib/charts/dashboard.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { phone } from "$lib/layout.svelte";

  // The range the panels show, and the one button that freezes them or brings them back to live.
  // - The range is a radio group: arrow keys move between ranges, as with native radio buttons.
  // - A phone shows the button's icon only, with its word as the label.
  let { dashboard }: { dashboard: Dashboard } = $props();

  let group: HTMLDivElement;

  const label = (minutes: number) => (minutes < 60 ? `${minutes}m` : `${minutes / 60}h`);

  async function step(event: KeyboardEvent, index: number) {
    const by = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (by === undefined) return;
    event.preventDefault();
    const options = dashboard.options;
    const next = (index + by + options.length) % options.length;
    dashboard.pick(options[next]);
    await tick();
    (group.children[next] as HTMLElement | undefined)?.focus();
  }

  function press() {
    if (dashboard.span === null) dashboard.pause();
    else dashboard.live();
  }
</script>

<div class="flex items-center gap-1.5">
  <div bind:this={group} role="radiogroup" aria-label="Range" class="inline-flex overflow-hidden rounded-md border text-xs">
    {#each dashboard.options as minutes, index (minutes)}
      {@const checked = dashboard.range === minutes}
      <button
        type="button"
        role="radio"
        aria-checked={checked}
        tabindex={checked ? 0 : -1}
        class="px-2 py-1 tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset
               {checked ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'}"
        onclick={() => dashboard.pick(minutes)}
        onkeydown={(event) => step(event, index)}
      >
        {label(minutes)}
      </button>
    {/each}
  </div>
  <Button size="sm" variant="outline" aria-label={phone.current ? dashboard.button : undefined} onclick={press}>
    {#if dashboard.span === null}
      <PauseIcon aria-hidden="true" />
    {:else if dashboard.span.by === "pause"}
      <PlayIcon aria-hidden="true" />
    {:else}
      <ZoomOutIcon aria-hidden="true" />
    {/if}
    {#if !phone.current}{dashboard.button}{/if}
  </Button>
</div>
