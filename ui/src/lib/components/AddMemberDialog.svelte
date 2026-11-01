<script lang="ts">
  import { untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { api, errorMessage, type AccountSummary, type MemberRead } from "$lib/api/client";
  import AccountSearch from "$lib/components/AccountSearch.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { ROLE_HELP, ROLE_NAMES } from "$lib/permissions";

  let {
    open = $bindable(false),
    workspaceId,
    members,
    onAdded,
  }: {
    open?: boolean;
    workspaceId: number;
    members: MemberRead[];
    onAdded: () => Promise<void>;
  } = $props();

  let chosen = $state<AccountSummary | null>(null);
  let role = $state<"viewer" | "operator">("viewer");
  let busy = $state(false);

  $effect(() => {
    if (open) {
      untrack(() => {
        chosen = null;
        role = "viewer";
      });
    }
  });

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!chosen) return;
    busy = true;
    const { error } = await api.POST("/api/workspaces/{workspace_id}/members", {
      params: { path: { workspace_id: workspaceId } },
      body: { user_id: chosen.id, role },
    });
    busy = false;
    if (error) {
      toast.error(errorMessage(error, "Couldn't add them"));
      return;
    }
    open = false;
    await onAdded();
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-md">
    <form class="space-y-4" onsubmit={submit}>
      <Dialog.Header>
        <Dialog.Title>Add a member</Dialog.Title>
        <Dialog.Description>Anyone with an approved vservx account.</Dialog.Description>
      </Dialog.Header>
      <div class="space-y-2">
        <Label for="member-search">Person</Label>
        <AccountSearch id="member-search" bind:chosen exclude={members.map((member) => member.user_id)} />
      </div>
      <div class="space-y-2">
        <Label for="member-role">Role</Label>
        <Select.Root type="single" bind:value={() => role, (value) => (role = value === "operator" ? "operator" : "viewer")}>
          <Select.Trigger id="member-role" class="w-full">{ROLE_NAMES[role]}</Select.Trigger>
          <Select.Content>
            <Select.Item value="viewer" label="Viewer" />
            <Select.Item value="operator" label="Operator" />
          </Select.Content>
        </Select.Root>
        <p class="text-xs text-muted-foreground">{ROLE_HELP[role]}</p>
      </div>
      <Dialog.Footer>
        <Button type="button" variant="outline" onclick={() => (open = false)}>Cancel</Button>
        <Button type="submit" disabled={busy || !chosen}>Add member</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
