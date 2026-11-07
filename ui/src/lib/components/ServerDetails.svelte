<script lang="ts">
  import { tick, untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { fade, slide } from "svelte/transition";
  import { api, errorMessage, type SavedKeyRead, type ServerRead, type ServerWatchRead } from "$lib/api/client";
  import CollapsibleSection from "$lib/components/CollapsibleSection.svelte";
  import ConnectionDetails from "$lib/components/ConnectionDetails.svelte";
  import GpuStrip from "$lib/components/GpuStrip.svelte";
  import InstanceDetails from "$lib/components/InstanceDetails.svelte";
  import InstanceTable from "$lib/components/InstanceTable.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { clockTime, secondsAgo } from "$lib/format";
  import { duration, easeOut } from "$lib/motion";
  import { every } from "$lib/poll";
  import { navigate } from "$lib/router.svelte";
  import { serverStatus, TONE_DOT, type Tone } from "$lib/servers";
  import { HISTORY_MINUTES, WATCH_POLL_MS } from "$lib/watch";

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

  // What vservx has seen on the server, asked for every 5 s while the tab is visible.
  let view = $state<ServerWatchRead | null>(null);
  let refreshing = $state(false);
  // Connection details follow the server's state until someone opens or closes them.
  let detailsChosen = $state<boolean | null>(null);

  const watched = $derived(!server.jump_only);
  const connected = $derived(view?.state === "connected");
  // The instance in the address, or the first one that isn't folded away as stopped.
  const selected = $derived(
    view?.instances.find((each) => each.name === instance) ??
      view?.instances.find((each) => each.state !== "stopped") ??
      view?.instances[0] ??
      null,
  );
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

  // A row clicked in the table brings its details into view at once; their own slide-up shows the change.
  // Polls and addresses leave the scroll alone.
  async function showInstance() {
    await tick();
    document.getElementById("section-instance")?.closest("section")?.scrollIntoView({ block: "nearest" });
  }
</script>

<article class="space-y-5" aria-labelledby="server-details-name">
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
    <div id="connection-details" class="rounded-lg border p-4" transition:slide={{ duration: duration(200), easing: easeOut }}>
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
    <!-- Anything not read just now stays, greyed, with when it was read. A rule above each section keeps them apart. -->
    <div
      class="space-y-5 transition-opacity duration-200 [&>section]:border-t [&>section]:pt-5 {connected ? '' : 'opacity-60'}"
      in:fade={{ duration: duration(150), easing: easeOut }}
    >
      <!-- GPUs first: a few tiles that say how full the server is, above a list that can grow long. -->
      {#if current.gpus?.length || current.gpu_message}
        <CollapsibleSection id="gpus" title={gpuTitle}>
          {#if current.gpus?.length}
            <GpuStrip gpus={current.gpus} />
          {:else}
            <p class="text-sm text-muted-foreground">{current.gpu_message}</p>
          {/if}
        </CollapsibleSection>
      {/if}

      {#if current.found_at}
        <CollapsibleSection id="instances" title={`Instances · ${current.instances.length}`}>
          {#snippet aside()}
            <!-- The header says how fresh a connected server is; this only dates what's left from before. -->
            {#if !connected && (current.read_at ?? current.found_at)}
              last read {clockTime((current.read_at ?? current.found_at) as string)}
            {/if}
          {/snippet}
          {#if current.instances.length > 0}
            <InstanceTable
              instances={current.instances}
              selected={selected?.name ?? null}
              hrefFor={instanceHref}
              onpick={showInstance}
            />
          {:else}
            <p class="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
              No vLLM containers found on this server
            </p>
          {/if}
        </CollapsibleSection>
        {#if selected}
          {@const ready = selected.state === "ready"}
          <CollapsibleSection id="instance" title={`Instance · ${selected.name}`}>
            {#snippet aside()}
              {#if ready}last {HISTORY_MINUTES} min{/if}
            {/snippet}
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
    </div>
  {/if}
</article>
