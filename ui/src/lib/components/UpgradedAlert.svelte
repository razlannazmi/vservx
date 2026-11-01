<script lang="ts">
  import XIcon from "@lucide/svelte/icons/x";
  import { api } from "$lib/api/client";
  import { localDateTime } from "$lib/format";

  // Old news after a week: someone signing in a month later doesn't need it.
  const SHOWN_FOR_MS = 7 * 24 * 60 * 60 * 1000;
  // Remembers the upgrade (by its time) this browser dismissed.
  const DISMISSED_KEY = "vservx.upgrade-dismissed";

  let upgrade = $state<{ upgraded_at: string; by: string } | null>(null);

  function dismissedAt(): string | null {
    try {
      return localStorage.getItem(DISMISSED_KEY);
    } catch {
      return null;
    }
  }

  async function load() {
    const { data } = await api.GET("/api/database");
    const last = data?.last_upgrade;
    if (!last || Date.now() - Date.parse(last.upgraded_at) > SHOWN_FOR_MS) return;
    if (dismissedAt() === last.upgraded_at) return;
    upgrade = last;
  }

  function dismiss() {
    if (!upgrade) return;
    try {
      localStorage.setItem(DISMISSED_KEY, upgrade.upgraded_at);
    } catch {
      // Storage blocked: it just comes back next time.
    }
    upgrade = null;
  }

  $effect(() => {
    void load();
  });
</script>

{#if upgrade}
  <div role="status" class="flex items-center gap-3 rounded-lg border bg-card px-3 py-2 text-sm">
    <span class="flex-1">Database upgraded on {localDateTime(upgrade.upgraded_at)} by {upgrade.by}</span>
    <button type="button" class="rounded-md p-1 text-muted-foreground hover:text-foreground focus-visible:outline-2"
            aria-label="Dismiss" onclick={dismiss}>
      <XIcon class="size-4" />
    </button>
  </div>
{/if}
