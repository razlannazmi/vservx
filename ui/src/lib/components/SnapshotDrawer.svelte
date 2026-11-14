<script lang="ts">
  import XIcon from "@lucide/svelte/icons/x";
  import { onMount, untrack } from "svelte";
  import { fly } from "svelte/transition";
  import {
    api,
    errorMessage,
    type SnapshotCompareRead,
    type SnapshotDetailRead,
    type SnapshotEntryRead,
  } from "$lib/api/client";
  import SnapshotChanges from "$lib/components/SnapshotChanges.svelte";
  import SnapshotCommand from "$lib/components/SnapshotCommand.svelte";
  import SnapshotCompare from "$lib/components/SnapshotCompare.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { localDateTime } from "$lib/format";
  import { duration, easeOut } from "$lib/motion";
  import type { DrawerState } from "$lib/snapshots";
  import { instanceKey, type InstanceRef } from "$lib/watch";

  // Snapshots of a server's containers, over the right of the page without blocking it: the charts
  // keep updating, and another row's icon switches it. Its state lives in the address (ServerDetails).
  let {
    workspaceId,
    serverId,
    serverName,
    pageInstance,
    drawer,
    onchange,
    onclose,
  }: {
    workspaceId: number;
    serverId: number;
    serverName: string;
    pageInstance: InstanceRef | null;
    drawer: DrawerState;
    onchange: (drawer: DrawerState) => void;
    onclose: () => void;
  } = $props();

  const titleId = "snapshot-drawer-title";
  // "This instance" shows the instance last opened, or the one selected on the page.
  const target = $derived(drawer.instance ?? pageInstance);
  const showing = $derived<DrawerState["view"]>(drawer.view === "instance" && target ? "instance" : "server");

  let entries = $state<SnapshotEntryRead[] | null>(null);
  let nextBefore = $state<string | null>(null);
  let listError = $state<string | null>(null);
  let detail = $state<SnapshotDetailRead | null>(null);
  let comparison = $state<SnapshotCompareRead | null>(null);
  let compareError = $state<string | null>(null);
  let swapped = $state(false);
  let picking = $state(untrack(() => drawer.compare !== null));
  let picks = $state<number[]>(untrack(() => (drawer.compare ? [...drawer.compare] : [])));
  let closeButton = $state<HTMLButtonElement | null>(null);

  // Answers that arrive after a newer question are dropped.
  let listRun = 0;
  let detailRun = 0;
  let compareRun = 0;

  const newest = $derived(entries?.[0] ?? null);
  // A removed instance's command is its last snapshot with a config.
  const lastLive = $derived(entries?.find((each) => each.kind !== "removed") ?? null);
  const detailId = $derived(showing === "instance" ? (drawer.at ?? lastLive?.id ?? null) : null);
  const listKey = $derived(`${serverId}|${showing}|${showing === "instance" && target ? instanceKey(target) : ""}`);
  const compareKey = $derived(drawer.compare ? drawer.compare.join(",") : "");
  const shown = $derived(
    comparison && swapped
      ? {
          from_snapshot: comparison.to_snapshot,
          to_snapshot: comparison.from_snapshot,
          differences: comparison.differences.map((each) => ({ ...each, before: each.after, after: each.before })),
        }
      : comparison,
  );

  onMount(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButton?.focus();
    return () => opener?.focus();
  });

  $effect(() => {
    void listKey;
    untrack(() => {
      entries = null;
      nextBefore = null;
      if (!drawer.compare) {
        picking = false;
        picks = [];
      }
      void loadList(false);
    });
  });

  $effect(() => {
    const id = detailId;
    untrack(() => void loadDetail(id));
  });

  $effect(() => {
    void compareKey;
    untrack(() => void loadCompare());
  });

  async function loadList(more: boolean) {
    const run = more ? listRun : ++listRun;
    const before = more ? (nextBefore ?? undefined) : undefined;
    const path = { workspace_id: workspaceId, server_id: serverId };
    const result =
      showing === "instance" && target
        ? await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/instances/{name}/snapshots", {
            params: { path: { ...path, name: target.name }, query: { before, source: target.source } },
          })
        : await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/snapshots", {
            params: { path, query: { before } },
          });
    if (run !== listRun) return;
    if (result.error || !result.data) {
      listError = errorMessage(result.error, "Couldn't load snapshots");
      return;
    }
    listError = null;
    entries = more && entries ? [...entries, ...result.data.entries] : result.data.entries;
    nextBefore = result.data.next_before;
  }

  async function loadDetail(id: number | null) {
    const run = ++detailRun;
    if (id === null) {
      detail = null;
      return;
    }
    const { data } = await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/snapshots/{snapshot_id}", {
      params: { path: { workspace_id: workspaceId, server_id: serverId, snapshot_id: id } },
    });
    if (run === detailRun) detail = data ?? null;
  }

  async function loadCompare() {
    const run = ++compareRun;
    swapped = false;
    const pair = drawer.compare;
    if (!pair) {
      comparison = null;
      compareError = null;
      return;
    }
    const { data, error } = await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/snapshots/compare", {
      params: { path: { workspace_id: workspaceId, server_id: serverId }, query: { from: pair[0], to: pair[1] } },
    });
    if (run !== compareRun) return;
    comparison = data ?? null;
    compareError = error ? errorMessage(error, "Couldn't compare these snapshots") : null;
  }

  function switchTo(view: DrawerState["view"]) {
    picking = false;
    picks = [];
    onchange({ view, instance: target, at: null, compare: null });
  }

  function togglePicking() {
    picks = [];
    picking = !picking;
    if (!picking && drawer.compare) onchange({ ...drawer, compare: null });
  }

  function pick(id: number) {
    let next = picks.includes(id) ? picks.filter((each) => each !== id) : [...picks, id];
    // A third pick replaces the oldest.
    if (next.length > 2) next = next.slice(-2);
    picks = next;
    onchange({ ...drawer, compare: next.length === 2 ? [next[0], next[1]] : null });
  }

  function open(entry: SnapshotEntryRead) {
    picking = false;
    picks = [];
    const opened = { source: entry.source, name: entry.instance };
    const current =
      showing === "instance" && target !== null && instanceKey(opened) === instanceKey(target) && entry.id === lastLive?.id;
    onchange({ view: "instance", instance: opened, at: current ? null : entry.id, compare: null });
  }

  const tab = "rounded-[5px] px-2 py-1 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
  const link =
    "rounded-sm underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring";
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key === "Escape" && !event.defaultPrevented) onclose();
  }}
/>

<div
  role="dialog"
  aria-modal="false"
  aria-labelledby={titleId}
  class="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l bg-background shadow-[-8px_0_24px_-12px_rgb(0_0_0/0.25)] sm:w-[28rem] lg:w-[32rem]"
  transition:fly={{ x: 48, duration: duration(200), easing: easeOut }}
>
  <header class="flex items-start justify-between gap-3 border-b px-4 py-3">
    <div class="min-w-0 space-y-2">
      <h2 id={titleId} class="truncate text-base font-semibold tracking-tight">
        Snapshots · <span class={showing === "instance" ? "font-mono" : ""}>{showing === "instance" ? target?.name : serverName}</span>
      </h2>
      <div class="inline-flex rounded-md border p-0.5 text-xs" role="group" aria-label="Show snapshots of">
        <button
          type="button"
          class="{tab} {showing === 'instance' ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground'}"
          aria-pressed={showing === "instance"}
          disabled={!target}
          onclick={() => switchTo("instance")}
        >
          This instance
        </button>
        <button
          type="button"
          class="{tab} {showing === 'server' ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground'}"
          aria-pressed={showing === "server"}
          onclick={() => switchTo("server")}
        >
          All on server
        </button>
      </div>
    </div>
    <button
      bind:this={closeButton}
      type="button"
      aria-label="Close snapshots"
      class="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      onclick={onclose}
    >
      <XIcon class="size-4" aria-hidden="true" />
    </button>
  </header>

  <div class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
    {#if drawer.compare}
      {#if shown}
        <SnapshotCompare comparison={shown} onswap={() => (swapped = !swapped)} />
      {:else if compareError}
        <p class="text-sm text-muted-foreground">{compareError}</p>
      {/if}
    {:else if showing === "instance"}
      <div class="space-y-3">
        <p class="text-xs text-muted-foreground">
          {#if drawer.at !== null && detail}
            As of {localDateTime(detail.happened_at)} ·
            <button type="button" class={link} onclick={() => onchange({ ...drawer, at: null })}>Back to current</button>
          {:else if newest?.kind === "removed"}
            Removed · noticed {localDateTime(newest.noticed_at)}{#if newest.last_seen}
              · last seen {localDateTime(newest.last_seen)}{/if}
          {:else if detail}
            Current · since {localDateTime(detail.happened_at)} · secrets are placeholders
          {/if}
        </p>
        {#if detail}
          <SnapshotCommand {workspaceId} {serverId} {detail} />
        {/if}
      </div>
    {/if}

    <section class="space-y-2" aria-labelledby="snapshot-changes">
      <div class="flex items-center justify-between gap-2">
        <h3 id="snapshot-changes" class="text-sm font-medium">Changes</h3>
        <Button size="xs" variant={picking ? "secondary" : "outline"} aria-pressed={picking} onclick={togglePicking}>
          Compare
        </Button>
      </div>
      {#if picking && picks.length < 2}
        <p class="text-xs text-muted-foreground">Pick two snapshots to compare.</p>
      {/if}
      {#if listError}
        <p class="text-sm text-muted-foreground">{listError}</p>
      {:else if entries === null}
        <p class="text-sm text-muted-foreground">Loading…</p>
      {:else}
        <SnapshotChanges
          {entries}
          showInstance={showing === "server"}
          {picking}
          {picks}
          onpick={pick}
          onopen={open}
          onmore={nextBefore ? () => void loadList(true) : null}
        />
      {/if}
    </section>
  </div>
</div>
