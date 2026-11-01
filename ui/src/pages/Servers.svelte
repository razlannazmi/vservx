<script lang="ts">
  import PlusIcon from "@lucide/svelte/icons/plus";
  import { onMount } from "svelte";
  import { fly } from "svelte/transition";
  import { api, type SavedKeyRead, type ServerRead } from "$lib/api/client";
  import ServerCard from "$lib/components/ServerCard.svelte";
  import ServerDetails from "$lib/components/ServerDetails.svelte";
  import ServerDialog from "$lib/components/ServerDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { duration } from "$lib/motion";
  import { canOperate } from "$lib/permissions";
  import { navigate } from "$lib/router.svelte";
  import { leaveMissingWorkspace, type Workspace } from "$lib/workspaces.svelte";

  let { workspace, serverId }: { workspace: Workspace; serverId: number | null } = $props();

  let servers = $state<ServerRead[]>([]);
  let keys = $state<SavedKeyRead[]>([]);
  let loaded = $state(false);
  let dialogOpen = $state(false);
  let editing = $state<ServerRead | null>(null);

  const operator = $derived(canOperate(workspace.role));
  const regular = $derived(servers.filter((each) => !each.jump_only));
  const jumpHosts = $derived(servers.filter((each) => each.jump_only));
  const selected = $derived(servers.find((each) => each.id === serverId) ?? null);
  const base = $derived(`/workspaces/${workspace.slug}`);

  onMount(() => {
    void load();
  });

  async function load() {
    const path = { workspace_id: workspace.id };
    const [serverReply, keyReply] = await Promise.all([
      api.GET("/api/workspaces/{workspace_id}/servers", { params: { path } }),
      api.GET("/api/workspaces/{workspace_id}/ssh-keys", { params: { path } }),
    ]);
    // The workspace is gone, or this person was removed from it.
    if (serverReply.response.status === 404) return leaveMissingWorkspace();
    servers = serverReply.data ?? [];
    keys = keyReply.data ?? [];
    loaded = true;
  }

  // Nothing chosen: the first card. A server that's gone: back to the workspace.
  $effect(() => {
    if (!loaded) return;
    const first = regular[0] ?? jumpHosts[0];
    if (serverId === null && first) navigate(`${base}/servers/${first.id}`, { replace: true });
    else if (serverId !== null && !selected) navigate(base, { replace: true });
  });

  function add() {
    editing = null;
    dialogOpen = true;
  }

  function edit(server: ServerRead) {
    editing = server;
    dialogOpen = true;
  }

  async function saved(server: ServerRead) {
    await load();
    navigate(`${base}/servers/${server.id}`);
  }

  async function deleted() {
    await load();
    navigate(base, { replace: true });
  }
</script>

{#snippet cards(list: ServerRead[])}
  <ul class="space-y-2">
    {#each list as server (server.id)}
      <li><ServerCard {server} href={`${base}/servers/${server.id}`} selected={server.id === serverId} /></li>
    {/each}
  </ul>
{/snippet}

<div class="flex min-h-0 flex-1 gap-5 p-5">
  <aside class="flex w-52 shrink-0 flex-col gap-3 overflow-y-auto" aria-label="Servers">
    <div class="space-y-2">
      <h1 class="truncate text-lg font-semibold tracking-tight" title={workspace.name}>{workspace.name}</h1>
      {#if operator}
        <Button size="sm" class="w-full" onclick={add}><PlusIcon /> Add server</Button>
      {/if}
    </div>
    {#if regular.length > 0}
      {@render cards(regular)}
    {/if}
    {#if jumpHosts.length > 0}
      <h2 class="pt-1 text-xs font-medium text-muted-foreground">Jump hosts</h2>
      {@render cards(jumpHosts)}
    {/if}
  </aside>

  <section class="min-w-0 flex-1 overflow-y-auto" aria-label="Server details">
    {#if loaded && servers.length === 0}
      <div class="flex h-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed p-8 text-center">
        <h2 class="text-lg font-semibold tracking-tight">No servers yet</h2>
        {#if operator}
          <Button onclick={add}><PlusIcon /> Add server</Button>
        {:else}
          <p class="text-sm text-muted-foreground">An operator can add servers</p>
        {/if}
      </div>
    {:else if selected}
      {#key selected.id}
        <div in:fly={{ y: 8, duration: duration(200) }}>
          <ServerDetails workspaceId={workspace.id} server={selected} {servers} {keys} {operator} onEdit={edit} onChanged={load} />
        </div>
      {/key}
    {/if}
  </section>
</div>

<ServerDialog
  bind:open={dialogOpen}
  workspaceId={workspace.id}
  server={editing}
  {servers}
  {keys}
  onSaved={saved}
  onDeleted={deleted}
  onKeyAdded={load}
/>
