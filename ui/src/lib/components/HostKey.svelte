<script lang="ts">
  import EyeIcon from "@lucide/svelte/icons/eye";
  import EyeOffIcon from "@lucide/svelte/icons/eye-off";

  // A host key fingerprint, hidden until asked for. The dots never hint at its length.
  let { fingerprint }: { fingerprint: string } = $props();

  let shown = $state(false);
  const label = $derived(shown ? "Hide host key" : "Show host key");
</script>

<span class="inline-flex max-w-full items-start gap-1.5 align-top">
  {#if shown}
    <span class="min-w-0 font-mono break-all">{fingerprint}</span>
  {:else}
    <span class="font-mono tracking-widest" aria-hidden="true">••••••••••••</span><span class="sr-only">hidden</span>
  {/if}
  <button type="button" onclick={() => (shown = !shown)} aria-label={label} aria-pressed={shown} title={label}
          class="shrink-0 rounded-sm p-0.5 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
    {#if shown}
      <EyeOffIcon class="size-3.5" />
    {:else}
      <EyeIcon class="size-3.5" />
    {/if}
  </button>
</span>
