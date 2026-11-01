<script lang="ts">
  import type { ServerRead } from "$lib/api/client";
  import { followLink } from "$lib/router.svelte";
  import { serverStatus, TONE_DOT } from "$lib/servers";

  let { server, href, selected }: { server: ServerRead; href: string; selected: boolean } = $props();

  const status = $derived(serverStatus(server));
</script>

<!-- The selected card is outlined in the text colour; hover lifts it a pixel (not under reduced motion). -->
<a
  {href}
  onclick={followLink}
  aria-current={selected ? "page" : undefined}
  class="block rounded-lg border bg-card px-3 py-2 text-sm outline-none transition-[translate,box-shadow,border-color] duration-200
         hover:shadow-sm focus-visible:ring-2 focus-visible:ring-ring motion-safe:hover:-translate-y-px
         {selected ? 'border-foreground ring-1 ring-foreground' : ''}"
>
  <span class="flex items-center gap-2 font-medium">
    <span class="size-2 shrink-0 rounded-full {TONE_DOT[status.tone]}" aria-hidden="true"></span>
    <span class="truncate">{server.name}</span>
  </span>
  <span class="mt-0.5 block truncate text-xs text-muted-foreground">{status.label}</span>
</a>
