<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { navigate } from "$lib/router.svelte";
  import { createWorkspace } from "$lib/workspaces.svelte";

  let { open = $bindable(false) }: { open?: boolean } = $props();

  let name = $state("");
  let busy = $state(false);
  let message = $state<string | null>(null);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    message = null;
    try {
      const workspace = await createWorkspace(name.trim());
      open = false;
      name = "";
      navigate(`/w/${workspace.id}`);
    } catch (error) {
      message = (error as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-sm">
    <form class="space-y-4" onsubmit={submit}>
      <Dialog.Header>
        <Dialog.Title>New workspace</Dialog.Title>
        <Dialog.Description>A fence around a set of servers, with its own members. You'll be its owner.</Dialog.Description>
      </Dialog.Header>
      <div class="space-y-2">
        <Label for="new-workspace-name">Name</Label>
        <Input id="new-workspace-name" required maxlength={255} placeholder="Home, Work, Cluster 1" bind:value={name} />
      </div>
      {#if message}
        <p role="alert" class="rounded-lg border px-3 py-2 text-sm">{message}</p>
      {/if}
      <Dialog.Footer>
        <Button type="button" variant="outline" onclick={() => (open = false)}>Cancel</Button>
        <Button type="submit" disabled={busy}>Create</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
