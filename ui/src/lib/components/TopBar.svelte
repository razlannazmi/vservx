<script lang="ts">
  import { followLink } from "$lib/router.svelte";

  // Phones only: the name at the top. Moving between workspaces sits by the thumb, above the tabs.
</script>

<header class="flex h-12 shrink-0 items-center border-b bg-sidebar px-4">
  <a href="/" onclick={followLink} class="inline-flex h-11 items-center rounded-md px-1 font-mono text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
    vservx
  </a>
</header>
