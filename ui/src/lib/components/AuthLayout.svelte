<script lang="ts">
  import type { Snippet } from "svelte";
  import HopChain from "$lib/components/HopChain.svelte";

  // Sign-in and sign-up: the hop chain on the left half (a strip on top on narrow screens), the form beside it.
  let { children }: { children: Snippet } = $props();
</script>

<div class="flex min-h-svh flex-col lg:flex-row">
  <HopChain />
  <main class="flex flex-1 items-center justify-center p-6">
    {@render children()}
  </main>
</div>
