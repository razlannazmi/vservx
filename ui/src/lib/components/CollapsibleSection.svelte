<script lang="ts">
  import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
  import { untrack, type Snippet } from "svelte";
  import { slide } from "svelte/transition";
  import { duration, easeOut } from "$lib/motion";

  // A titled section that folds away; each browser remembers which ones are folded.
  // The title is in the text colour so each section starts clearly, above content that's mostly 12px.
  let { id, title, aside, children }: { id: string; title: string; aside?: Snippet; children: Snippet } = $props();

  const storageKey = $derived(`vservx.section.${id}`);
  let open = $state(untrack(() => !isFolded(`vservx.section.${id}`)));

  function isFolded(key: string): boolean {
    try {
      return localStorage.getItem(key) === "folded";
    } catch {
      return false; // Storage can be off (private windows, blocked site data): open is the default.
    }
  }

  function toggle() {
    open = !open;
    try {
      if (open) localStorage.removeItem(storageKey);
      else localStorage.setItem(storageKey, "folded");
    } catch {
      // Not remembered this time; the section still folds.
    }
  }
</script>

<section aria-labelledby="section-{id}">
  <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
    <h3 id="section-{id}" class="text-sm font-semibold">
      <button
        type="button"
        class="group -ml-1 inline-flex items-center gap-1 rounded-md px-1 outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-expanded={open}
        aria-controls="section-{id}-body"
        onclick={toggle}
      >
        <ChevronDownIcon
          class="size-4 text-muted-foreground transition-transform duration-200 ease-out group-hover:text-foreground motion-reduce:transition-none {open ? '' : '-rotate-90'}"
          aria-hidden="true"
        />
        {title}
      </button>
    </h3>
    {#if aside}
      <div class="text-xs text-muted-foreground">{@render aside()}</div>
    {/if}
  </div>
  {#if open}
    <div id="section-{id}-body" class="pt-2" transition:slide={{ duration: duration(200), easing: easeOut }}>
      {@render children()}
    </div>
  {/if}
</section>
