<script lang="ts">
  import { untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { slide } from "svelte/transition";
  import { api, errorMessage, type SavedKeyRead, type ServerRead, type ServerWatchRead } from "$lib/api/client";
  import CollapsibleSection from "$lib/components/CollapsibleSection.svelte";
  import ConnectionDetails from "$lib/components/ConnectionDetails.svelte";
  import GpuStrip from "$lib/components/GpuStrip.svelte";
  import InstanceDetails from "$lib/components/InstanceDetails.svelte";
  import InstanceTable from "$lib/components/InstanceTable.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { clockTime, secondsAgo } from "$lib/format";
  import { duration } from "$lib/motion";
  import { every } from "$lib/poll";
  import { navigate } from "$lib/router.svelte";
  import { routeOf, serverStatus, TONE_DOT, type Tone } from "$lib/servers";
  import { formatNumber, WATCH_POLL_MS } from "$lib/watch";

  let {
    workspaceId,
    server,
    servers,
    keys,
    operator,
    onEdit,
    onChanged,
    instance,
    base,
  }: {
    workspaceId: number;
    server: ServerRead;
    servers: ServerRead[];
    keys: SavedKeyRead[];
    operator: boolean;
    onEdit: (server: ServerRead) => void;
    onChanged: () => Promise<void>;
    instance: string | null;
    base: string;
  } = $props();

  // What vservx has seen on the server, asked for every 10 s while the tab is visible.
  let view = $state<ServerWatchRead | null>(null);
  let refreshing = $state(false);
  // Connection details follow the server's state until someone opens or closes them.
  let detailsChosen = $state<boolean | null>(null);

  const watched = $derived(!server.jump_only);
  const route = $derived(routeOf(server, servers).join(" → "));
  const connected = $derived(view?.state === "connected");
  // The instance in the address, or the first one.
  const selected = $derived(view?.instances.find((each) => each.name === instance) ?? view?.instances[0] ?? null);
  const detailsOpen = $derived(
    detailsChosen ??
      (server.jump_only ||
        !server.host_key_fingerprint ||
        server.last_test?.failure === "host_key_changed" ||
        view?.state === "not_tested" ||
        view?.state === "host_key_changed"),
  );

  // The line under the name: how watching is going, or the problem in words.
  const status = $derived.by((): { tone: Tone; label: string } => {
    if (!watched) return serverStatus(server);
    const current = view;
    if (!current) return { tone: "none", label: "Checking…" };
    switch (current.state) {
      case "connected":
        return { tone: "ok", label: current.read_at ? `Connected · read ${secondsAgo(current.read_at)}` : "Connected" };
      case "checking":
        return { tone: "none", label: "Checking…" };
      case "not_tested":
        return { tone: "none", label: "Not tested yet" };
      case "unreachable":
        return { tone: "bad", label: current.since ? `Unreachable · since ${clockTime(current.since)}` : "Unreachable" };
      case "sign_in_failed":
        return { tone: "bad", label: "Sign-in failed" };
      case "host_key_changed":
        return { tone: "warn", label: "Host key changed" };
      case "jump_only":
        return serverStatus(server);
    }
  });

  const gpuTitle = $derived.by(() => {
    const gpus = view?.gpus ?? [];
    if (gpus.length === 0) return "GPUs";
    return new Set(gpus.map((each) => each.name)).size === 1
      ? `GPUs · ${gpus.length} × ${gpus[0].name}`
      : `GPUs · ${gpus.length}`;
  });

  $effect(() => {
    if (server.jump_only) return;
    const serverId = server.id;
    return untrack(() => every(WATCH_POLL_MS, () => loadView(serverId)));
  });

  // An address naming a container the server no longer has falls back to the server, once it's been looked at.
  $effect(() => {
    if (!view?.found_at || instance === null) return;
    if (!view.instances.some((each) => each.name === instance)) {
      navigate(`${base}/servers/${server.id}`, { replace: true });
    }
  });

  async function loadView(serverId: number = server.id) {
    const { data } = await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/watch", {
      params: { path: { workspace_id: workspaceId, server_id: serverId } },
    });
    if (data && data.server_id === server.id) view = data;
  }

  async function refresh() {
    refreshing = true;
    const { data, error } = await api.POST("/api/workspaces/{workspace_id}/servers/{server_id}/refresh", {
      params: { path: { workspace_id: workspaceId, server_id: server.id } },
    });
    refreshing = false;
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't refresh"));
      return;
    }
    view = data;
  }

  // A test or an accepted key can start (or stop) the watching: ask again straight away.
  async function connectionChanged() {
    await onChanged();
    if (watched) await loadView();
  }

  function instanceHref(name: string): string {
    return `${base}/servers/${server.id}/instances/${encodeURIComponent(name)}`;
  }
</script>

<article class="space-y-5 rounded-xl border bg-card p-5" aria-labelledby="server-details-name">
  <header class="space-y-2">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0 space-y-1">
        <h2 id="server-details-name" class="truncate text-lg font-semibold tracking-tight">{server.name}</h2>
        <p class="font-mono text-sm break-all text-muted-foreground">{server.username}@{server.host}:{server.port}</p>
      </div>
      <div class="flex shrink-0 gap-2">
        {#if watched}
          <Button size="sm" variant="outline" onclick={refresh} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </Button>
        {/if}
        {#if operator}
          <Button size="sm" variant="outline" onclick={() => onEdit(server)}>Edit</Button>
        {/if}
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span class="flex items-center gap-1.5 text-foreground">
        <span class="size-2 shrink-0 rounded-full {TONE_DOT[status.tone]}" aria-hidden="true"></span>{status.label}
      </span>
      <span>route <span class="font-mono">{route}</span></span>
      {#if view?.docker === "sudo"}
        <span>docker via sudo</span>
      {/if}
      <button
        type="button"
        class="rounded-sm underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        aria-expanded={detailsOpen}
        aria-controls="connection-details"
        onclick={() => (detailsChosen = !detailsOpen)}
      >
        Connection details
      </button>
    </div>
    {#if view && !connected && view.message}
      <p class="text-xs text-muted-foreground">{view.message}</p>
    {/if}
  </header>

  {#if detailsOpen}
    <div id="connection-details" class="rounded-lg border p-4" transition:slide={{ duration: duration(200) }}>
      <ConnectionDetails {workspaceId} {server} {servers} {keys} {operator} onChanged={connectionChanged} />
    </div>
  {/if}

  {#if view?.docker_message}
    <p class="flex items-start gap-2 rounded-lg border border-warn-border bg-warn-bg px-4 py-3 text-sm">
      <span class="mt-1.5 size-2 shrink-0 rounded-full bg-status-warn" aria-hidden="true"></span>
      {view.docker_message}
    </p>
  {/if}

  {#if watched && view}
    {@const current = view}
    <!-- Anything not read just now stays, greyed, with when it was read. -->
    <div class="space-y-5 transition-opacity duration-200 {connected ? '' : 'opacity-60'}">
      {#if current.found_at}
        <CollapsibleSection id="instances" title={`Instances · ${current.instances.length}`}>
          {#snippet aside()}
            {#if connected && current.found_at}
              found {secondsAgo(current.found_at)} · usage every {formatNumber(current.usage_interval_seconds)} s
            {:else if current.read_at ?? current.found_at}
              last read {clockTime((current.read_at ?? current.found_at) as string)}
            {/if}
          {/snippet}
          {#if current.instances.length > 0}
            <InstanceTable instances={current.instances} selected={selected?.name ?? null} hrefFor={instanceHref} />
          {:else}
            <p class="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
              No vLLM containers found on this server
            </p>
          {/if}
        </CollapsibleSection>
        {#if selected}
          <CollapsibleSection id="instance" title={selected.name}>
            <InstanceDetails {workspaceId} serverId={server.id} instance={selected} />
          </CollapsibleSection>
        {/if}
      {:else if current.state === "not_tested"}
        <p class="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          Run a connection test to start watching this server
        </p>
      {:else if (current.state === "connected" || current.state === "checking") && !current.docker_message}
        <p class="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          Looking for instances…
        </p>
      {/if}

      {#if current.gpus?.length || current.gpu_message}
        <CollapsibleSection id="gpus" title={gpuTitle}>
          {#if current.gpus?.length}
            <GpuStrip gpus={current.gpus} />
          {:else}
            <p class="text-sm text-muted-foreground">{current.gpu_message}</p>
          {/if}
        </CollapsibleSection>
      {/if}
    </div>
  {/if}
</article>
