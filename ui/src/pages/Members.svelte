<script lang="ts">
  import CheckIcon from "@lucide/svelte/icons/check";
  import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
  import PlusIcon from "@lucide/svelte/icons/plus";
  import { onMount } from "svelte";
  import { slide } from "svelte/transition";
  import { toast } from "svelte-sonner";
  import { api, errorMessage, type MemberRead, type WorkspaceRead } from "$lib/api/client";
  import AddMemberDialog from "$lib/components/AddMemberDialog.svelte";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { duration, easeOut } from "$lib/motion";
  import { isOwner, ROLE_COVERAGE, ROLE_NAMES } from "$lib/permissions";
  import { session } from "$lib/session.svelte";
  import { leaveMissingWorkspace } from "$lib/workspaces.svelte";

  let { workspace }: { workspace: WorkspaceRead } = $props();

  // Least to most, left to right.
  const ROLES = ["viewer", "operator", "owner"] as const;

  let members = $state<MemberRead[]>([]);
  let loaded = $state(false);
  let adding = $state(false);
  let removing = $state<MemberRead | null>(null);
  let confirmRemove = $state(false);
  let confirmLeave = $state(false);
  // The roles table is reference: closed until asked for.
  let showRoles = $state(false);

  const owner = $derived(isOwner(workspace.role));
  const me = $derived(session.user?.id ?? null);
  const path = $derived({ workspace_id: workspace.id });
  // The owner first, then by name.
  const sorted = $derived(
    [...members].sort((a, b) => Number(isOwner(b.role)) - Number(isOwner(a.role)) || a.name.localeCompare(b.name)),
  );

  onMount(() => {
    void load();
  });

  async function load() {
    const { data, response } = await api.GET("/api/workspaces/{workspace_id}/members", { params: { path } });
    // The workspace is gone, or this person was removed from it.
    if (response.status === 404) return leaveMissingWorkspace();
    members = data ?? [];
    loaded = true;
  }

  async function changeRole(member: MemberRead, role: string) {
    if (role === member.role) return;
    const { error } = await api.PATCH("/api/workspaces/{workspace_id}/members/{user_id}", {
      params: { path: { ...path, user_id: member.user_id } },
      body: { role: role === "operator" ? "operator" : "viewer" },
    });
    if (error) toast.error(errorMessage(error, "Couldn't change the role"));
    await load();
  }

  function askToRemove(member: MemberRead) {
    removing = member;
    confirmRemove = true;
  }

  async function remove() {
    if (!removing) return;
    const { error } = await api.DELETE("/api/workspaces/{workspace_id}/members/{user_id}", {
      params: { path: { ...path, user_id: removing.user_id } },
    });
    if (error) throw new Error(errorMessage(error, "Couldn't remove them"));
    await load();
  }

  async function leave() {
    if (me === null) return;
    const { error } = await api.DELETE("/api/workspaces/{workspace_id}/members/{user_id}", {
      params: { path: { ...path, user_id: me } },
    });
    if (error) throw new Error(errorMessage(error, "Couldn't leave the workspace"));
    await leaveMissingWorkspace();
  }
</script>

<div class="flex-1 overflow-y-auto p-4 md:p-6">
  <div class="mx-auto max-w-3xl space-y-6">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div class="space-y-1.5">
        <h1 class="text-xl font-semibold tracking-tight">Members</h1>
        <p class="text-sm text-muted-foreground">Who can see {workspace.name}, and what each of them can do.</p>
      </div>
      {#if owner}
        <Button onclick={() => (adding = true)}><PlusIcon /> Add member</Button>
      {:else}
        <Button variant="outline" onclick={() => (confirmLeave = true)}>Leave workspace</Button>
      {/if}
    </header>

    {#if loaded}
      <ul class="divide-y rounded-xl border bg-card">
        {#each sorted as member (member.user_id)}
          <li class="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
            <div class="min-w-0 flex-1">
              <p class="truncate font-medium">
                {member.name}{#if member.user_id === me}{" "}<span class="font-normal text-muted-foreground">(you)</span>{/if}
              </p>
              <p class="truncate font-mono text-xs text-muted-foreground">{member.email}</p>
            </div>
            {#if owner && !isOwner(member.role)}
              <Select.Root type="single" bind:value={() => member.role, (role) => changeRole(member, role)}>
                <Select.Trigger size="sm" class="w-28" aria-label={`Role of ${member.name}`}>{ROLE_NAMES[member.role]}</Select.Trigger>
                <Select.Content>
                  <Select.Item value="viewer" label="Viewer" />
                  <Select.Item value="operator" label="Operator" />
                </Select.Content>
              </Select.Root>
              <Button size="sm" variant="ghost" onclick={() => askToRemove(member)}>Remove</Button>
            {:else}
              <span class="text-muted-foreground">{ROLE_NAMES[member.role]}</span>
            {/if}
          </li>
        {/each}
      </ul>

      <section class="rounded-xl border bg-card" aria-labelledby="members-roles">
        <h2 id="members-roles">
          <button type="button" aria-expanded={showRoles} aria-controls="members-roles-table"
                  onclick={() => (showRoles = !showRoles)}
                  class={`flex w-full items-center justify-between gap-2 px-4 py-3 text-left font-medium outline-none
                    hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring ${showRoles ? "rounded-t-xl" : "rounded-xl"}`}>
            What each role can do
            <ChevronDownIcon class={`size-4 text-muted-foreground transition-transform duration-200 ease-out ${showRoles ? "rotate-180" : ""}`} />
          </button>
        </h2>
        {#if showRoles}
          <div id="members-roles-table" class="border-t" transition:slide={{ duration: duration(200), easing: easeOut }}>
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head class="pl-4"><span class="sr-only">Action</span></Table.Head>
                  {#each ROLES as role (role)}
                    <Table.Head class="text-center last:pr-4 md:w-24">{ROLE_NAMES[role]}</Table.Head>
                  {/each}
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each ROLE_COVERAGE as row (row.label)}
                  <Table.Row>
                    <!-- The label wraps, so on a phone the table fits instead of scrolling sideways. -->
                    <Table.Cell class="pl-4 whitespace-normal">{row.label}</Table.Cell>
                    {#each ROLES as role (role)}
                      <Table.Cell class="text-center last:pr-4">
                        {#if row.roles.includes(role)}
                          <CheckIcon class="mx-auto size-4" /><span class="sr-only">Yes</span>
                        {:else}
                          <span class="text-muted-foreground" aria-hidden="true">–</span><span class="sr-only">No</span>
                        {/if}
                      </Table.Cell>
                    {/each}
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </div>
        {/if}
      </section>
    {/if}
  </div>
</div>

<AddMemberDialog bind:open={adding} workspaceId={workspace.id} {members} onAdded={load} />
<ConfirmDialog
  bind:open={confirmRemove}
  title={`Remove ${removing?.name ?? ""}?`}
  message={`They lose access to ${workspace.name}. You can add them again later.`}
  confirmLabel="Remove"
  onConfirm={remove}
/>
<ConfirmDialog
  bind:open={confirmLeave}
  title={`Leave ${workspace.name}?`}
  message="You lose access to its servers. The owner can add you again."
  confirmLabel="Leave workspace"
  onConfirm={leave}
/>
