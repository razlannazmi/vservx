<script lang="ts">
  import ChevronLeftIcon from "@lucide/svelte/icons/chevron-left";
  import HistoryIcon from "@lucide/svelte/icons/history";
  import { tick, untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { fade, slide } from "svelte/transition";
  import { api, errorMessage, type SavedKeyRead, type ServerRead, type ServerWatchRead } from "$lib/api/client";
  import CollapsibleSection from "$lib/components/CollapsibleSection.svelte";
  import ConnectionDetails from "$lib/components/ConnectionDetails.svelte";
  import GpuStrip from "$lib/components/GpuStrip.svelte";
  import InstanceDetails from "$lib/components/InstanceDetails.svelte";
  import InstanceTable from "$lib/components/InstanceTable.svelte";
  import SnapshotDrawer from "$lib/components/SnapshotDrawer.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { clockTime, localDateTime, secondsAgo } from "$lib/format";
  import { phone } from "$lib/layout.svelte";
  import { duration, easeOut } from "$lib/motion";
  import { every } from "$lib/poll";
  import { followLink, instancePath, navigate, router } from "$lib/router.svelte";
  import { serverAddress, serverStatus, TONE_DOT, type Tone } from "$lib/servers";
  import { drawerSearch, readDrawer, type DrawerState } from "$lib/snapshots";
  import {
    HISTORY_MINUTES,
    instanceKey,
    NEEDS_ADMIN_OWNER,
    NEEDS_ADMIN_OWNER_DETAIL,
    WATCH_POLL_MS,
    type InstanceRef,
  } from "$lib/watch";

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
    instance: InstanceRef | null;
    base: string;
  } = $props();

  // What vservx has seen on the server, asked for every 5 s while the tab is visible.
  let view = $state<ServerWatchRead | null>(null);
  let refreshing = $state(false);
  // Connection details follow the server's state until someone opens or closes them.
  let detailsChosen = $state<boolean | null>(null);

  // The snapshots drawer, kept in the query string so a link can open it.
  let drawer = $state<DrawerState | null>(readDrawer(location.search));

  const watched = $derived(!server.jump_only);
  const connected = $derived(view?.state === "connected");
  // The address names an instance by its source and name: a system and a --user vllm.service are two.
  const named = (each: InstanceRef) => instance !== null && instanceKey(each) === instanceKey(instance);
  // A container removed in the last 7 days, when the address names one.
  const selectedRemoved = $derived(view?.removed.find(named) ?? null);
  // The instance in the address, or (unless it names a removed one) the first that isn't folded away as stopped.
  const selected = $derived.by(() => {
    if (!view) return null;
    const found = view.instances.find(named);
    if (found || selectedRemoved) return found ?? null;
    return view.instances.find((each) => each.state !== "stopped") ?? view.instances[0] ?? null;
  });
  const selectedRef = $derived.by((): InstanceRef | null => {
    const open = selected ?? selectedRemoved;
    return open && { source: open.source, name: open.name };
  });
  const selectedKey = $derived(selectedRef && instanceKey(selectedRef));

  // The address is the page's (with an instance's ?source=), then the drawer's query.
  $effect(() => {
    const search = drawerSearch(drawer);
    const page = router.path;
    untrack(() => {
      const next = search === "" ? page : `${page}${page.includes("?") ? "&" : "?"}${search.slice(1)}`;
      if (location.pathname + location.search !== next) history.replaceState(null, "", next);
    });
  });

  // Another server's page starts with the drawer closed.
  let drawerServer = untrack(() => server.id);
  $effect(() => {
    const serverId = server.id;
    untrack(() => {
      if (serverId !== drawerServer) {
        drawerServer = serverId;
        drawer = null;
      }
    });
  });
  const detailsOpen = $derived(
    detailsChosen ??
      (server.jump_only ||
        (server.kind === "ssh" && !server.host_key_fingerprint) ||
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
      case "needs_admin_owner":
        return { tone: "warn", label: NEEDS_ADMIN_OWNER };
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

  // An address naming a container the server no longer has falls back to the server, once it's been
  // looked at. A container removed in the last 7 days keeps its address.
  $effect(() => {
    if (!view?.found_at || instance === null) return;
    if (!view.instances.some(named) && !view.removed.some(named)) {
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

  function instanceHref(each: InstanceRef): string {
    return `${base}/servers/${server.id}/${instancePath(each)}`;
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
    <!-- Phones show one server at a time; this leads back to the list. -->
    <a
      href={base}
      onclick={followLink}
      class="-ml-1 inline-flex items-center gap-0.5 rounded-md px-1 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:hidden"
    >
      <ChevronLeftIcon class="size-4" aria-hidden="true" />Servers
    </a>
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0 space-y-1">
        <h2 id="server-details-name" class="truncate text-lg font-semibold tracking-tight">{server.name}</h2>
        <p class="font-mono text-sm break-all text-muted-foreground">{serverAddress(server)}</p>
      </div>
      <div class="flex shrink-0 gap-2">
        {#if watched}
          <Button size="sm" variant="outline" onclick={refresh} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onclick={() => (drawer = { view: "server", instance: selectedRef, at: null, compare: null })}
          >
            <HistoryIcon aria-hidden="true" />Snapshots
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
    {#if view?.state === "needs_admin_owner"}
      <p class="text-xs text-muted-foreground">{NEEDS_ADMIN_OWNER_DETAIL}</p>
    {:else if view && !connected && view.message}
      <p class="text-xs text-muted-foreground">{view.message}</p>
    {/if}
    {#if view?.systemd === "unavailable"}
      <p class="text-xs text-muted-foreground">systemd: {view.systemd_message}</p>
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
      <!-- GPUs first: a few tiles that say how full the server is, above a list that can grow long.
           On a phone they come last, so whether the containers are up is the first thing seen. -->
      {#snippet gpus()}
        {#if current.gpus?.length || current.gpu_message}
          <CollapsibleSection id="gpus" title={gpuTitle}>
            {#if current.gpus?.length}
              <GpuStrip gpus={current.gpus} />
            {:else}
              <p class="text-sm text-muted-foreground">{current.gpu_message}</p>
            {/if}
          </CollapsibleSection>
        {/if}
      {/snippet}
      {#if !phone.current}{@render gpus()}{/if}

      {#if current.found_at}
        <CollapsibleSection id="instances" title={`Instances · ${current.instances.length}`}>
          {#snippet aside()}
            <!-- The header says how fresh a connected server is; this only dates what's left from before. -->
            {#if !connected && (current.read_at ?? current.found_at)}
              last read {clockTime((current.read_at ?? current.found_at) as string)}
            {/if}
          {/snippet}
          {#if current.instances.length > 0 || current.removed.length > 0}
            <InstanceTable
              instances={current.instances}
              removed={current.removed}
              selected={selectedKey}
              hrefFor={instanceHref}
              onpick={showInstance}
              onsnapshots={(each) =>
                (drawer = { view: "instance", instance: { source: each.source, name: each.name }, at: null, compare: null })}
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
        {:else if selectedRemoved}
          <CollapsibleSection id="instance" title={`Instance · ${selectedRemoved.name}`}>
            <p class="text-sm text-muted-foreground">
              Removed · last seen {localDateTime(selectedRemoved.last_seen)}. Its last launch command is under Snapshots.
            </p>
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
      {#if phone.current}{@render gpus()}{/if}
    </div>
  {/if}
</article>

{#if drawer}
  <SnapshotDrawer
    {workspaceId}
    serverId={server.id}
    serverName={server.name}
    pageInstance={selectedRef}
    {drawer}
    onchange={(next) => (drawer = next)}
    onclose={() => (drawer = null)}
  />
{/if}
