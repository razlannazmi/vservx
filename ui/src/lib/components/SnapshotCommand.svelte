<script lang="ts">
  import InfoIcon from "@lucide/svelte/icons/info";
  import { toast } from "svelte-sonner";
  import { slide } from "svelte/transition";
  import { api, errorMessage, type SnapshotDetailRead } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { duration, easeOut } from "$lib/motion";
  import { copyText } from "$lib/snapshots";

  // One snapshot's rebuilt command with Copy, what it covers, and its API key fingerprint with Check a key.
  let { workspaceId, serverId, detail }: { workspaceId: number; serverId: number; detail: SnapshotDetailRead } =
    $props();

  // What the rebuild covers, behind the info button so it doesn't crowd the command.
  let coversOpen = $state(false);
  let checking = $state(false);
  let candidate = $state("");
  let answer = $state<string | null>(null);
  let busy = $state(false);

  // Another snapshot shown: the check starts over.
  $effect(() => {
    void detail.id;
    checking = false;
    candidate = "";
    answer = null;
  });

  async function copy(text: string) {
    if (await copyText(text)) toast.success("Copied");
    else toast.error("Couldn't copy. Select the command and copy it.");
  }

  async function check(event: SubmitEvent) {
    event.preventDefault();
    if (!candidate) return;
    busy = true;
    const { data, error } = await api.POST(
      "/api/workspaces/{workspace_id}/servers/{server_id}/snapshots/{snapshot_id}/check-key",
      { params: { path: { workspace_id: workspaceId, server_id: serverId, snapshot_id: detail.id } }, body: { key: candidate } },
    );
    busy = false;
    candidate = "";
    if (error || !data) answer = errorMessage(error, "Couldn't check the key");
    else if (data.matches === null) answer = data.reason;
    else answer = data.matches ? "Matches" : "Doesn't match";
  }
</script>

{#if detail.command}
  <!-- The buttons get their own strip above the command, so they never sit over its text or scrollbars. -->
  <div class="overflow-hidden rounded-lg border">
    <div class="flex items-center justify-between gap-1 border-b bg-background px-2 py-1.5">
      <span class="text-xs text-muted-foreground">{detail.source === "docker" ? "" : "Unit file"}</span>
      <div class="flex items-center gap-1">
        <Button
          size="icon-xs"
          variant="outline"
          class="dark:bg-background"
          aria-label="What this command covers"
          title="What this command covers"
          aria-expanded={coversOpen}
          aria-controls="snapshot-covers"
          onclick={() => (coversOpen = !coversOpen)}
        >
          <InfoIcon aria-hidden="true" />
        </Button>
        <Button size="xs" variant="outline" class="dark:bg-background" onclick={() => copy(detail.command ?? "")}>
          Copy
        </Button>
      </div>
    </div>
    <pre class="max-h-80 overflow-auto bg-muted/40 p-3 font-mono text-xs leading-5">{detail.command}</pre>
  </div>
  {#if coversOpen}
    <p
      id="snapshot-covers"
      class="rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
      transition:slide={{ duration: duration(150), easing: easeOut }}
    >
      {detail.covers}
    </p>
  {/if}
{/if}
{#if detail.compose}
  <p class="text-xs text-muted-foreground">{detail.compose}</p>
{/if}
{#if detail.env_hidden}
  <p class="text-xs text-muted-foreground">{detail.env_hidden}</p>
{/if}

{#if detail.key_fingerprint}
  <div class="space-y-2 text-xs">
    <div class="flex flex-wrap items-center gap-2">
      <span>API key fingerprint <code class="font-mono break-all">{detail.key_fingerprint}</code></span>
      {#if !checking}
        <button
          type="button"
          class="rounded-sm text-muted-foreground underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          onclick={() => (checking = true)}
        >
          Check a key
        </button>
      {/if}
    </div>
    {#if checking}
      <p class="text-muted-foreground">
        A short code made from the vLLM API key this container runs with. The key itself isn't stored. Use Check a
        key to test whether a key you have is that one.
      </p>
      <form class="flex flex-wrap items-center gap-2" onsubmit={check}>
        <Input
          type="password"
          bind:value={candidate}
          placeholder="Paste a key"
          aria-label="Key to check"
          autocomplete="off"
          class="h-7 w-full text-xs sm:w-56 md:text-xs"
        />
        <Button size="sm" variant="outline" type="submit" disabled={busy || !candidate}>Check</Button>
        {#if answer}
          <span role="status">{answer}</span>
        {/if}
      </form>
    {/if}
  </div>
{/if}
