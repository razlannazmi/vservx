<script lang="ts">
  import { onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import { api, errorMessage, type MemberRead, type WorkspaceRead } from "$lib/api/client";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { isOwner } from "$lib/permissions";
  import { navigate } from "$lib/router.svelte";
  import { leaveMissingWorkspace, loadWorkspaces } from "$lib/workspaces.svelte";

  let { workspace }: { workspace: WorkspaceRead } = $props();

  let name = $state("");
  let renaming = $state(false);
  let members = $state<MemberRead[]>([]);
  // The member chosen to become the owner, by user id.
  let heir = $state("");
  let confirmHandOver = $state(false);
  let confirmDelete = $state(false);

  const path = $derived({ workspace_id: workspace.id });
  const candidates = $derived(members.filter((member) => !isOwner(member.role)));
  const heirMember = $derived(candidates.find((member) => String(member.user_id) === heir) ?? null);

  onMount(() => {
    name = workspace.name;
    void loadMembers();
  });

  async function loadMembers() {
    const { data, response } = await api.GET("/api/workspaces/{workspace_id}/members", { params: { path } });
    if (response.status === 404) return leaveMissingWorkspace();
    members = data ?? [];
  }

  async function rename(event: SubmitEvent) {
    event.preventDefault();
    renaming = true;
    const { error } = await api.PATCH("/api/workspaces/{workspace_id}", { params: { path }, body: { name: name.trim() } });
    renaming = false;
    if (error) {
      toast.error(errorMessage(error, "Couldn't rename the workspace"));
      return;
    }
    await loadWorkspaces();
    toast.success("Workspace renamed");
  }

  async function handOver() {
    if (!heirMember) return;
    const { error } = await api.POST("/api/workspaces/{workspace_id}/owner", {
      params: { path },
      body: { user_id: heirMember.user_id },
    });
    if (error) throw new Error(errorMessage(error, "Couldn't hand the workspace over"));
    // Now an operator here, so Settings goes away; the members page shows the new owner.
    await loadWorkspaces();
    navigate(`/w/${workspace.id}/members`, { replace: true });
  }

  async function remove() {
    const { error } = await api.DELETE("/api/workspaces/{workspace_id}", { params: { path } });
    if (error) throw new Error(errorMessage(error, "Couldn't delete the workspace"));
    await leaveMissingWorkspace();
  }
</script>

<div class="flex-1 overflow-y-auto p-6">
  <div class="mx-auto max-w-2xl space-y-6">
    <header class="space-y-1">
      <h1 class="text-xl font-semibold tracking-tight">Settings</h1>
      <p class="text-sm text-muted-foreground">Only the owner can change these.</p>
    </header>

    <section class="space-y-3 rounded-xl border bg-card p-5" aria-labelledby="settings-name">
      <h2 id="settings-name" class="font-medium">Name</h2>
      <form class="flex gap-2" onsubmit={rename}>
        <Input aria-label="Workspace name" required maxlength={255} bind:value={name} />
        <Button type="submit" variant="outline" disabled={renaming || name.trim() === workspace.name}>Rename</Button>
      </form>
    </section>

    <section class="space-y-3 rounded-xl border bg-card p-5" aria-labelledby="settings-hand-over">
      <div class="space-y-1">
        <h2 id="settings-hand-over" class="font-medium">Hand over</h2>
        <p class="text-sm text-muted-foreground">Make another member the owner. You stay on as an operator.</p>
      </div>
      {#if candidates.length === 0}
        <p class="text-sm text-muted-foreground">Only a member can become the owner: add someone on the Members page first.</p>
      {:else}
        <div class="flex gap-2">
          <Select.Root type="single" bind:value={heir}>
            <Select.Trigger class="w-full" aria-label="New owner">{heirMember ? heirMember.name : "Choose a member"}</Select.Trigger>
            <Select.Content>
              {#each candidates as member (member.user_id)}
                <Select.Item value={String(member.user_id)} label={`${member.name} · ${member.email}`} />
              {/each}
            </Select.Content>
          </Select.Root>
          <Button variant="outline" disabled={!heirMember} onclick={() => (confirmHandOver = true)}>Hand over</Button>
        </div>
      {/if}
    </section>

    <section class="space-y-3 rounded-xl border bg-card p-5" aria-labelledby="settings-delete">
      <div class="space-y-1">
        <h2 id="settings-delete" class="font-medium">Delete workspace</h2>
        <p class="text-sm text-muted-foreground">
          Its servers and saved keys are deleted from vservx and every member loses access. The servers themselves
          aren't touched.
        </p>
      </div>
      <Button variant="outline" onclick={() => (confirmDelete = true)}>Delete workspace</Button>
    </section>
  </div>
</div>

<ConfirmDialog
  bind:open={confirmHandOver}
  title={`Hand ${workspace.name} to ${heirMember?.name ?? ""}?`}
  message="They become its owner and you become an operator. Only they can hand it back."
  confirmLabel="Hand over"
  onConfirm={handOver}
/>
<ConfirmDialog
  bind:open={confirmDelete}
  title={`Delete ${workspace.name}?`}
  message="Everything in it goes, and this can't be undone."
  confirmLabel="Delete workspace"
  requireText={workspace.name}
  onConfirm={remove}
/>
