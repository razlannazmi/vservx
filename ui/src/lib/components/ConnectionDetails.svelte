<script lang="ts">
  import { toast } from "svelte-sonner";
  import { api, errorMessage, type ConnectionTestResult, type SavedKeyRead, type ServerRead } from "$lib/api/client";
  import ConnectionResult from "$lib/components/ConnectionResult.svelte";
  import HostKey from "$lib/components/HostKey.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { localDateTime, relativeTime } from "$lib/format";
  import { routeOf } from "$lib/servers";

  // How vservx reaches the server: what it signs in with, the route, the host key, and the latest test.
  let {
    workspaceId,
    server,
    servers,
    keys,
    operator,
    onChanged,
  }: {
    workspaceId: number;
    server: ServerRead;
    servers: ServerRead[];
    keys: SavedKeyRead[];
    operator: boolean;
    onChanged: () => Promise<void>;
  } = $props();

  // The test run here, hop by hop; until then, the summary the server remembers.
  let run = $state<ConnectionTestResult | null>(null);
  let testing = $state(false);
  let accepting = $state(false);

  const key = $derived(keys.find((each) => each.id === server.ssh_key_id) ?? null);
  const signsInWith = $derived(
    server.auth_type === "password" ? "password" : key ? `saved key “${key.name}”` : "a saved key",
  );
  const route = $derived(routeOf(server, servers).join(" → "));
  // From this page's own run, the hop whose key changed: it carries the key presented now.
  const changedHop = $derived.by(() => {
    const last = run && !run.ok ? run.hops.at(-1) : undefined;
    return last?.reason === "host_key_changed" ? last : null;
  });
  const keyChanged = $derived(run ? changedHop !== null : server.last_test?.failure === "host_key_changed");
  const changedName = $derived(changedHop?.name ?? server.last_test?.failed_hop ?? server.name);

  async function test() {
    testing = true;
    const { data, error } = await api.POST("/api/workspaces/{workspace_id}/servers/{server_id}/test", {
      params: { path: { workspace_id: workspaceId, server_id: server.id } },
    });
    testing = false;
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't run the test"));
      return;
    }
    run = data;
    // The card's status and the recorded host key come from the server's own record.
    await onChanged();
  }

  async function acceptKey() {
    if (!changedHop?.fingerprint || changedHop.server_id === null) return;
    accepting = true;
    // The key may be a jump host's in front of this server: it's accepted on that one.
    const { error } = await api.POST("/api/workspaces/{workspace_id}/servers/{server_id}/host-key/accept", {
      params: { path: { workspace_id: workspaceId, server_id: changedHop.server_id } },
      body: { fingerprint: changedHop.fingerprint },
    });
    accepting = false;
    if (error) {
      toast.error(errorMessage(error, "Couldn't accept the new key"));
      return;
    }
    await test();
  }
</script>

<div class="space-y-4">
  <dl class="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
    <dt class="text-muted-foreground">Signs in with</dt>
    <dd>{signsInWith}</dd>
    <dt class="text-muted-foreground">Route</dt>
    <dd class="font-mono break-words">{route}</dd>
    <dt class="text-muted-foreground">Host key</dt>
    <dd>
      {#if server.host_key_fingerprint}
        <span class="font-mono">{server.host_key_type}</span> · <HostKey fingerprint={server.host_key_fingerprint} />
        {#if server.host_key_recorded_at}
          <span class="text-muted-foreground" title={localDateTime(server.host_key_recorded_at)}>
            · recorded {relativeTime(server.host_key_recorded_at)}</span>
        {/if}
      {:else}
        <span class="text-muted-foreground">not recorded yet</span>
      {/if}
    </dd>
  </dl>

  {#if keyChanged}
    <div class="space-y-2 rounded-lg border border-warn-border bg-warn-bg px-4 py-3 text-sm">
      <p class="flex items-center gap-2 font-medium">
        <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span> Host key changed
      </p>
      <p>
        {changedName} presents a different host key from the one vservx recorded, so vservx won't connect to it until the
        new key is accepted. Accept it only if you know why it changed, for example after a reinstall.
      </p>
      {#if changedHop?.fingerprint}
        <p>It now presents <span class="font-mono break-all">{changedHop.fingerprint}</span></p>
        {#if operator}
          <Button size="sm" onclick={acceptKey} disabled={accepting || testing}>{accepting ? "Accepting…" : "Accept new key"}</Button>
        {/if}
      {:else}
        <p class="text-muted-foreground">Test the connection to see the key it presents now.</p>
      {/if}
    </div>
  {/if}

  <section class="space-y-2" aria-labelledby="server-details-test">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h4 id="server-details-test" class="text-sm font-medium text-muted-foreground">Latest test</h4>
      <Button size="sm" onclick={test} disabled={testing || accepting}>{testing ? "Testing…" : "Test connection"}</Button>
    </div>
    {#if run}
      <ConnectionResult result={run} />
    {:else if server.last_test}
      <ConnectionResult result={server.last_test} />
    {:else}
      <p class="text-sm text-muted-foreground">Never tested.</p>
    {/if}
  </section>
</div>
