<script lang="ts">
  import { onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import { api, errorMessage, type AccountSummary, type AdminWorkspaceRead } from "$lib/api/client";
  import AccountSearch from "$lib/components/AccountSearch.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { loadWorkspaces } from "$lib/workspaces.svelte";

  let list = $state<AdminWorkspaceRead[]>([]);
  let loaded = $state(false);
  let changing = $state<AdminWorkspaceRead | null>(null);
  let dialogOpen = $state(false);
  let chosen = $state<AccountSummary | null>(null);
  let busy = $state(false);

  onMount(() => {
    void load();
  });

  async function load() {
    const { data } = await api.GET("/api/admin/workspaces");
    list = data ?? [];
    loaded = true;
  }

  function askToChange(workspace: AdminWorkspaceRead) {
    changing = workspace;
    chosen = null;
    dialogOpen = true;
  }

  async function changeOwner(event: SubmitEvent) {
    event.preventDefault();
    if (!changing || !chosen) return;
    busy = true;
    const { error } = await api.POST("/api/admin/workspaces/{workspace_id}/owner", {
      params: { path: { workspace_id: changing.id } },
      body: { user_id: chosen.id },
    });
    busy = false;
    if (error) {
      toast.error(errorMessage(error, "Couldn't change the owner"));
      return;
    }
    dialogOpen = false;
    await load();
    // The new owner may be you, which adds the workspace to your sidebar.
    await loadWorkspaces();
  }
</script>

<div class="flex-1 overflow-y-auto p-6">
  <div class="mx-auto max-w-5xl space-y-6">
    <header class="space-y-1">
      <h1 class="text-xl font-semibold tracking-tight">Workspaces</h1>
      <p class="text-sm text-muted-foreground">
        Every workspace in vservx. You see inside only the ones you're a member of.
      </p>
    </header>

    {#if loaded && list.length === 0}
      <p class="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">No workspaces yet</p>
    {:else if list.length > 0}
      <div class="rounded-xl border bg-card">
        <Table.Root>
          <Table.Header>
            <Table.Row>
              <Table.Head class="pl-4">Name</Table.Head>
              <Table.Head>Owner</Table.Head>
              <Table.Head>Members</Table.Head>
              <Table.Head class="pr-4"><span class="sr-only">Actions</span></Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each list as workspace (workspace.id)}
              <Table.Row>
                <Table.Cell class="pl-4 font-medium">{workspace.name}</Table.Cell>
                <Table.Cell>
                  {#if workspace.owner}
                    {workspace.owner.name} <span class="font-mono text-xs text-muted-foreground">{workspace.owner.email}</span>
                  {:else}
                    <span class="text-muted-foreground">none</span>
                  {/if}
                </Table.Cell>
                <Table.Cell class="tabular-nums">{workspace.member_count}</Table.Cell>
                <Table.Cell class="pr-4 text-right">
                  <Button size="sm" variant="ghost" onclick={() => askToChange(workspace)}>Change owner</Button>
                </Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
    {/if}
  </div>
</div>

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content class="sm:max-w-md">
    <form class="space-y-4" onsubmit={changeOwner}>
      <Dialog.Header>
        <Dialog.Title>Change the owner of {changing?.name}</Dialog.Title>
        <Dialog.Description>
          Any approved account. They join if they aren't a member, and the current owner stays on as an operator.
        </Dialog.Description>
      </Dialog.Header>
      <div class="space-y-2">
        <Label for="new-owner-search">New owner</Label>
        <AccountSearch id="new-owner-search" bind:chosen exclude={changing?.owner ? [changing.owner.id] : []} />
      </div>
      <Dialog.Footer>
        <Button type="button" variant="outline" onclick={() => (dialogOpen = false)}>Cancel</Button>
        <Button type="submit" disabled={busy || !chosen}>Change owner</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
