<script lang="ts">
  import type { Snippet } from "svelte";

  // Panels two to a row once there's room for both, one per row otherwise.
  // - It measures its own width, not the window's: the details pane is far narrower than the window on desktop.
  // - An expanded panel spans both columns itself.
  let { children }: { children: Snippet } = $props();
</script>

<div class="@container">
  <div class="grid gap-3 @min-[40rem]:grid-cols-2">
    {@render children()}
  </div>
</div>
