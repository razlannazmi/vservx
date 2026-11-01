<script lang="ts">
  import { onMount } from "svelte";
  import { api, type DatabaseRead } from "$lib/api/client";
  import { localDateTime } from "$lib/format";

  let info = $state<DatabaseRead | null>(null);

  const STATE_WORDS: Record<DatabaseRead["state"], string> = {
    new: "New",
    current: "Up to date",
    upgrade_required: "Upgrade waiting",
    newer_than_app: "From a newer vservx",
  };

  onMount(() => {
    void load();
  });

  async function load() {
    const { data } = await api.GET("/api/database");
    info = data ?? null;
  }
</script>

<div class="flex-1 overflow-y-auto p-6">
  <div class="mx-auto max-w-3xl space-y-6">
    <header class="space-y-1">
      <h1 class="text-xl font-semibold tracking-tight">Database</h1>
      <p class="text-sm text-muted-foreground">Which version of the tables this vservx runs on, and its upgrades.</p>
    </header>

    {#if info}
      <dl class="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-4 gap-y-3 rounded-xl border bg-card p-5 text-sm">
        <dt class="text-muted-foreground">Status</dt>
        <dd>{STATE_WORDS[info.state]}</dd>
        <dt class="text-muted-foreground">Current revision</dt>
        <dd class="font-mono">{info.current_revision ?? "none"}</dd>
        <dt class="text-muted-foreground">Latest available</dt>
        <dd class="font-mono">{info.head_revision}</dd>
        <dt class="text-muted-foreground">Last upgrade</dt>
        <dd>
          {#if info.last_upgrade}
            {localDateTime(info.last_upgrade.upgraded_at)} by {info.last_upgrade.by}
            <span class="font-mono text-muted-foreground">· {info.last_upgrade.from_revision} → {info.last_upgrade.to_revision}</span>
          {:else}
            <span class="text-muted-foreground">none yet</span>
          {/if}
        </dd>
        <dt class="text-muted-foreground">Newest backup</dt>
        <dd>
          {#if info.latest_backup}
            <span class="font-mono break-all">{info.latest_backup.name}</span>
            <span class="text-muted-foreground">· {localDateTime(info.latest_backup.created_at)}</span>
          {:else}
            <span class="text-muted-foreground">none yet</span>
          {/if}
        </dd>
      </dl>
      <p class="text-sm text-muted-foreground">
        A backup is made before every upgrade and kept in the <span class="font-mono">backups</span> folder next to the
        database. vservx never deletes them.
      </p>
    {/if}
  </div>
</div>
