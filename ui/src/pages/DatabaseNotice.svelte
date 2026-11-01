<script lang="ts">
  import { api, errorMessage, type DatabaseRead } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button/index.js";
  import { loadSession, session, signOut } from "$lib/session.svelte";
  import SignIn from "./SignIn.svelte";

  let info = $state<DatabaseRead | null>(null);
  let busy = $state(false);
  let failure = $state<string | null>(null);

  const isAdmin = $derived(session.user?.role === "admin");

  $effect(() => {
    if (isAdmin && session.database === "upgrade_required") void load();
  });

  async function load() {
    const { data } = await api.GET("/api/database");
    info = data ?? null;
  }

  async function upgrade() {
    busy = true;
    failure = null;
    const { error } = await api.POST("/api/database/upgrade");
    busy = false;
    if (error) {
      failure = errorMessage(error, "The upgrade failed");
      return;
    }
    // The app loads as normal now.
    await loadSession();
  }
</script>

{#if session.database === "upgrade_required" && !session.user}
  <SignIn note="vservx was updated and its database needs an upgrade. An admin can sign in to run it." />
{:else}
  <div class="flex min-h-svh items-center justify-center p-6">
    <section class="w-full max-w-lg space-y-5">
      <p class="font-mono text-sm text-muted-foreground">vservx</p>

      {#if session.database === "newer_than_app"}
        <h1 class="text-2xl font-semibold tracking-tight">This database comes from a newer vservx</h1>
        <p class="text-sm text-muted-foreground">
          A newer version of vservx has already upgraded this database, so this version can't use it.
          Run that newer version again, or restore a backup from before the upgrade (backups are kept
          in the <span class="font-mono">backups</span> folder next to the database).
        </p>
      {:else if isAdmin}
        <h1 class="text-2xl font-semibold tracking-tight">The database needs an upgrade</h1>
        <p class="text-sm text-muted-foreground">
          This version of vservx changes the database before it can be used. Nobody else can sign in
          until it's done.
        </p>
        {#if info && info.pending.length > 0}
          <div class="space-y-2">
            <h2 class="text-sm font-medium">What will change</h2>
            <ul class="list-disc space-y-1 pl-5 text-sm">
              {#each info.pending as change (change)}
                <li>{change}</li>
              {/each}
            </ul>
          </div>
        {/if}
        <p class="text-sm">A backup of the database is made first.</p>
        {#if failure}
          <p role="alert" class="rounded-lg border px-3 py-2 text-sm">{failure}</p>
        {/if}
        <Button onclick={upgrade} disabled={busy}>{busy ? "Upgrading…" : "Upgrade now"}</Button>
      {:else}
        <h1 class="text-2xl font-semibold tracking-tight">An admin needs to upgrade the database.</h1>
        <p class="text-sm text-muted-foreground">
          vservx was updated. Once an admin has upgraded the database, reload this page.
        </p>
      {/if}

      {#if session.user}
        <Button variant="outline" onclick={signOut}>Sign out</Button>
      {/if}
    </section>
  </div>
{/if}
