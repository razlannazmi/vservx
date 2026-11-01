<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { navigate } from "$lib/router.svelte";
  import { createWorkspace } from "$lib/workspaces.svelte";

  let name = $state("");
  let busy = $state(false);
  let message = $state<string | null>(null);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    message = null;
    try {
      const workspace = await createWorkspace(name.trim());
      navigate(`/w/${workspace.id}`, { replace: true });
    } catch (error) {
      message = (error as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="flex flex-1 items-center justify-center p-6">
  <form class="w-full max-w-sm space-y-5" onsubmit={submit}>
    <div class="space-y-1">
      <h1 class="text-2xl font-semibold tracking-tight">You're not in any workspaces yet</h1>
      <p class="text-sm text-muted-foreground">
        A workspace keeps a set of servers, and the people who can see them, apart from the rest.
      </p>
    </div>
    <div class="space-y-2">
      <Label for="welcome-workspace-name">Workspace name</Label>
      <Input id="welcome-workspace-name" required maxlength={255} placeholder="Home, Work, Cluster 1" bind:value={name} />
    </div>
    {#if message}
      <p role="alert" class="rounded-lg border px-3 py-2 text-sm">{message}</p>
    {/if}
    <Button type="submit" class="w-full" disabled={busy}>Create workspace</Button>
    <p class="text-sm text-muted-foreground">A workspace owner can also add you.</p>
  </form>
</div>
