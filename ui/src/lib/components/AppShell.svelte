<script lang="ts">
  import type { Snippet } from "svelte";
  import Sidebar from "$lib/components/Sidebar.svelte";
  import UpgradedAlert from "$lib/components/UpgradedAlert.svelte";

  let { children }: { children: Snippet } = $props();
</script>

<div class="flex h-svh">
  <Sidebar />
  <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
    <div class="px-6 pt-4 empty:hidden"><UpgradedAlert /></div>
    {@render children()}
  </main>
</div>
