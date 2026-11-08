<script lang="ts">
  import PlusIcon from "@lucide/svelte/icons/plus";
  import { onMount, untrack } from "svelte";
  import { fly } from "svelte/transition";
  import { api, type SavedKeyRead, type ServerRead, type WatchSummaryRead } from "$lib/api/client";
  import ServerCard from "$lib/components/ServerCard.svelte";
  import ServerDetails from "$lib/components/ServerDetails.svelte";
  import ServerDialog from "$lib/components/ServerDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { phone } from "$lib/layout.svelte";
  import { duration, easeOut } from "$lib/motion";
  import { canOperate } from "$lib/permissions";
  import { every } from "$lib/poll";
  import { navigate } from "$lib/router.svelte";
  import { WATCH_POLL_MS } from "$lib/watch";
  import { leaveMissingWorkspace, type Workspace } from "$lib/workspaces.svelte";

  let {
    workspace,
    serverId,
    instance,
  }: { workspace: Workspace; serverId: number | null; instance: string | null } = $props();

  let servers = $state<ServerRead[]>([]);
  let keys = $state<SavedKeyRead[]>([]);
  let loaded = $state(false);
  // Each server's watch summary, for its card; asked for every 5 s while the tab is visible.
  let summaries = $state.raw(new Map<number, WatchSummaryRead>());
  let dialogOpen = $state(false);
  let editing = $state<ServerRead | null>(null);

  const operator = $derived(canOperate(workspace.role));
  const regular = $derived(servers.filter((each) => !each.jump_only));
  const jumpHosts = $derived(servers.filter((each) => each.jump_only));
  const selected = $derived(servers.find((each) => each.id === serverId) ?? null);
  const base = $derived(`/workspaces/${workspace.slug}`);
  // On a phone one column shows at a time: the details for a chosen server, the empty state when there
  // are none (it has its own "Add server"), otherwise the list.
  const empty = $derived(loaded && servers.length === 0);
  const showDetails = $derived(serverId !== null || empty);

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

  $effect(() => {
    const workspaceId = workspace.id;
    return untrack(() => every(WATCH_POLL_MS, () => loadSummaries(workspaceId)));
  });

  async function loadSummaries(workspaceId: number = workspace.id) {
    const { data } = await api.GET("/api/workspaces/{workspace_id}/watch", {
      params: { path: { workspace_id: workspaceId } },
    });
    if (data) summaries = new Map(data.map((each) => [each.server_id, each]));
  }

  // Saving, deleting or testing a server changes what's watched: the cards catch up straight away.
  async function changed() {
    await load();
    await loadSummaries();
  }

  // Nothing chosen: the first card (on a phone, the list itself is the page). A server that's gone:
  // back to the workspace.
  $effect(() => {
    if (!loaded) return;
    const first = regular[0] ?? jumpHosts[0];
    if (serverId === null && first && !phone.current) navigate(`${base}/servers/${first.id}`, { replace: true });
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
    await changed();
    navigate(`${base}/servers/${server.id}`);
  }

  async function deleted() {
    await changed();
    navigate(base, { replace: true });
  }
</script>

{#snippet cards(list: ServerRead[])}
  <ul class="space-y-2">
    {#each list as server (server.id)}
      <li>
        <ServerCard
          {server}
          href={`${base}/servers/${server.id}`}
          selected={server.id === serverId}
          summary={summaries.get(server.id)}
        />
      </li>
    {/each}
  </ul>
{/snippet}

<!-- On a phone, the list and one server's details are two screens: the address says which. -->
<div class="flex min-h-0 flex-1 gap-5 p-4 md:p-5">
  <!-- -m-1/p-1 keep focus rings unclipped. On a phone the list fills the row with flex-1, not w-full: w-full
       plus the negative margins would sit it 8px off-centre. -->
  <aside class="-m-1 flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-1 md:w-54 md:flex-none {showDetails ? 'max-md:hidden' : ''}" aria-label="Servers">
    <div class="space-y-2">
      <h1 class="truncate text-lg font-semibold tracking-tight" title={workspace.name}>{workspace.name}</h1>
      {#if operator}
        <Button size="sm" variant="outline" class="w-full" onclick={add}><PlusIcon /> Add server</Button>
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

  <!-- The 8px gutter keeps focus rings at the edges from being clipped by the scrolling, without narrowing the content. -->
  <section
    class="-mx-2 min-w-0 flex-1 overflow-y-auto px-2 {showDetails ? '' : 'max-md:hidden'}"
    aria-label="Server details"
  >
    {#if empty}
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
        <div in:fly={{ y: 8, duration: duration(200), easing: easeOut }}>
          <ServerDetails
            workspaceId={workspace.id}
            server={selected}
            {servers}
            {keys}
            {operator}
            onEdit={edit}
            onChanged={changed}
            {instance}
            {base}
          />
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
