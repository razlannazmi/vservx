<script lang="ts">
  import PlusIcon from "@lucide/svelte/icons/plus";
  import { onMount } from "svelte";
  import { api, errorMessage, type SavedKeyRead, type WorkspaceRead } from "$lib/api/client";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import KeyDialog from "$lib/components/KeyDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { canOperate } from "$lib/permissions";
  import { leaveMissingWorkspace } from "$lib/workspaces.svelte";

  let { workspace }: { workspace: WorkspaceRead } = $props();

  let keys = $state<SavedKeyRead[]>([]);
  let loaded = $state(false);
  let keyDialogOpen = $state(false);
  let replacing = $state<SavedKeyRead | null>(null);
  let deleting = $state<SavedKeyRead | null>(null);
  let confirmOpen = $state(false);

  const operator = $derived(canOperate(workspace.role));
  const path = $derived({ workspace_id: workspace.id });

  onMount(() => {
    void load();
  });

  async function load() {
    const { data, response } = await api.GET("/api/workspaces/{workspace_id}/ssh-keys", { params: { path } });
    // The workspace is gone, or this person was removed from it.
    if (response.status === 404) return leaveMissingWorkspace();
    keys = data ?? [];
    loaded = true;
  }

  function add() {
    replacing = null;
    keyDialogOpen = true;
  }

  function replace(key: SavedKeyRead) {
    replacing = key;
    keyDialogOpen = true;
  }

  function askToDelete(key: SavedKeyRead) {
    deleting = key;
    confirmOpen = true;
  }

  async function remove() {
    if (!deleting) return;
    const { error } = await api.DELETE("/api/workspaces/{workspace_id}/ssh-keys/{key_id}", {
      params: { path: { ...path, key_id: deleting.id } },
    });
    // Refused while a server still signs in with it: the backend says how many.
    if (error) throw new Error(errorMessage(error, "Couldn't delete the key"));
    await load();
  }
</script>

<div class="flex-1 overflow-y-auto p-4 md:p-6">
  <div class="mx-auto max-w-5xl space-y-6">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div class="space-y-1.5">
        <h1 class="text-xl font-semibold tracking-tight">Keys</h1>
        <p class="text-sm text-muted-foreground">Private keys this workspace's servers sign in with. vservx never shows them.</p>
      </div>
      {#if operator}
        <Button onclick={add}><PlusIcon /> Add key</Button>
      {/if}
    </header>

    {#if loaded && keys.length === 0}
      <p class="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">No saved keys yet</p>
    {:else if keys.length > 0}
      <!-- Phones: one row per key, its details stacked; the table needs more width than a phone has. -->
      <ul class="divide-y rounded-xl border bg-card md:hidden">
        {#each keys as key (key.id)}
          <li class="px-4 py-3 text-sm">
            <p class="flex items-baseline justify-between gap-3">
              <span class="min-w-0 truncate font-medium">{key.name}</span>
              <span class="shrink-0 text-xs text-muted-foreground tabular-nums">
                {key.server_count} {key.server_count === 1 ? "server" : "servers"}
              </span>
            </p>
            <p class="mt-0.5 font-mono text-xs break-all text-muted-foreground">{key.key_type} · {key.fingerprint}</p>
            <p class="text-xs text-muted-foreground">passphrase: {key.has_passphrase ? "yes" : "no"}</p>
            {#if operator}
              <div class="mt-2 flex gap-2">
                <Button size="sm" variant="outline" onclick={() => replace(key)}>Replace</Button>
                <Button size="sm" variant="outline" onclick={() => askToDelete(key)}>Delete</Button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
      <div class="hidden rounded-xl border bg-card md:block">
        <Table.Root>
          <Table.Header>
            <Table.Row>
              <Table.Head class="pl-4">Name</Table.Head>
              <Table.Head>Type</Table.Head>
              <Table.Head>Fingerprint</Table.Head>
              <Table.Head>Used by</Table.Head>
              <Table.Head>Passphrase</Table.Head>
              {#if operator}
                <Table.Head class="pr-4"><span class="sr-only">Actions</span></Table.Head>
              {/if}
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each keys as key (key.id)}
              <Table.Row>
                <Table.Cell class="pl-4 font-medium">{key.name}</Table.Cell>
                <Table.Cell class="font-mono text-xs">{key.key_type}</Table.Cell>
                <Table.Cell class="font-mono text-xs">{key.fingerprint}</Table.Cell>
                <Table.Cell class="tabular-nums">{key.server_count} {key.server_count === 1 ? "server" : "servers"}</Table.Cell>
                <Table.Cell>{key.has_passphrase ? "Yes" : "No"}</Table.Cell>
                {#if operator}
                  <Table.Cell class="pr-4 text-right">
                    <Button size="sm" variant="ghost" onclick={() => replace(key)}>Replace</Button>
                    <Button size="sm" variant="ghost" onclick={() => askToDelete(key)}>Delete</Button>
                  </Table.Cell>
                {/if}
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
    {/if}
  </div>
</div>

<KeyDialog bind:open={keyDialogOpen} workspaceId={workspace.id} {replacing} onSaved={load} />
<ConfirmDialog
  bind:open={confirmOpen}
  title={`Delete “${deleting?.name ?? ""}”?`}
  message="vservx forgets this key. It refuses while a server still signs in with it."
  confirmLabel="Delete"
  onConfirm={remove}
/>
