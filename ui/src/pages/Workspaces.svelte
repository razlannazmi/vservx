<script lang="ts">
  import PlusIcon from "@lucide/svelte/icons/plus";
  import { untrack } from "svelte";
  import { api, type WorkspaceOverviewRead } from "$lib/api/client";
  import NewWorkspaceDialog from "$lib/components/NewWorkspaceDialog.svelte";
  import WorkspaceIcon from "$lib/components/WorkspaceIcon.svelte";
  import { overviewCard, type StatusCount } from "$lib/overview";
  import { ROLE_NAMES } from "$lib/permissions";
  import { every } from "$lib/poll";
  import { followLink } from "$lib/router.svelte";
  import { TONE_DOT } from "$lib/servers";
  import { WATCH_POLL_MS } from "$lib/watch";
  import { workspaces } from "$lib/workspaces.svelte";

  let overviews = $state(new Map<number, WorkspaceOverviewRead>());
  // Until the first answer, every card says "checking…"; after it, a workspace missing from the
  // answer (created since) has no servers yet.
  let loaded = $state(false);
  let creating = $state(false);
  // The card under the pointer or focus: its icon plays.
  let hovered = $state<number | null>(null);

  const count = $derived(workspaces.list.length);

  $effect(() => untrack(() => every(WATCH_POLL_MS, load)));

  async function load() {
    const { data } = await api.GET("/api/workspaces/overview");
    // A failed poll keeps what's on screen; the next one tries again.
    if (!data) return;
    overviews = new Map(data.map((each) => [each.workspace_id, each]));
    loaded = true;
  }
</script>

<!-- One row of the counts grid: its name, then a count and dot per status. Every row has the same columns, so they
     line up. A zero stays in its column, faded. -->
{#snippet counts(name: string, row: StatusCount[])}
  <span class="pr-1 text-muted-foreground">{name}</span>
  {#each row as each (each.tone)}
    <span
      class={["flex items-center justify-end gap-1.5 tabular-nums", each.count === 0 && "opacity-50"]}
      title={`${each.count} ${each.words}`}
    >
      {each.count}
      <span class={`size-2 shrink-0 rounded-full ${TONE_DOT[each.tone]}`} aria-hidden="true"></span>
      <span class="sr-only">{each.words}</span>
    </span>
  {/each}
{/snippet}

<div class="flex-1 overflow-y-auto p-6">
  <div class="mx-auto max-w-6xl space-y-6">
    <header class="space-y-1.5">
      <h1 class="text-xl font-semibold tracking-tight">Workspaces</h1>
      <p class="text-sm text-muted-foreground">{count === 1 ? "1 workspace" : `${count} workspaces`}</p>
    </header>

    <ul class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {#each workspaces.list as workspace (workspace.id)}
        {@const card = overviewCard(overviews.get(workspace.id), loaded)}
        <li>
          <a
            href={`/workspaces/${workspace.slug}`}
            onclick={followLink}
            onpointerenter={() => (hovered = workspace.id)}
            onpointerleave={() => (hovered = null)}
            onfocus={() => (hovered = workspace.id)}
            onblur={() => (hovered = null)}
            class="relative flex h-full min-h-44 flex-col gap-2.5 overflow-hidden rounded-xl border bg-card p-4 text-sm
              outline-none transition-colors duration-200 ease-out hover:border-foreground/25 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <!-- Half of it shows: centred on the right edge, cut by the card. -->
            <WorkspaceIcon
              name={workspace.icon}
              size={150}
              animate={hovered === workspace.id}
              class="absolute top-1/2 right-0 translate-x-1/2 -translate-y-1/2 -rotate-12 text-foreground opacity-[0.07]"
            />
            <div class="relative flex items-center justify-between gap-2">
              <span class="truncate text-base font-semibold">{workspace.name}</span>
              <span class="shrink-0 rounded-full border bg-card px-2 py-0.5 text-[11px] text-muted-foreground">
                {ROLE_NAMES[workspace.role]}
              </span>
            </div>

            {#if card.checking}
              <p class="relative text-muted-foreground">checking…</p>
            {:else if card.empty}
              <p class="relative text-muted-foreground">No servers yet</p>
            {:else}
              {#if card.servers && card.instances}
                <div class="relative grid w-fit grid-cols-[auto_repeat(4,auto)] items-center gap-x-4 gap-y-2">
                  {@render counts("servers", card.servers)}
                  {@render counts("instances", card.instances)}
                </div>
              {/if}
              {#if card.gpus}
                <div class="relative space-y-1">
                  <p class="flex justify-between gap-2 text-xs text-muted-foreground">
                    <span class="truncate">{card.gpus.label}{card.gpus.memory ? " · memory" : ""}</span>
                    {#if card.gpus.memory}<span class="shrink-0 tabular-nums">{card.gpus.memory}</span>{/if}
                  </p>
                  {#if card.gpus.percent !== null}
                    <div class="h-1.5 overflow-hidden rounded-full bg-muted">
                      <div class="h-full rounded-full bg-foreground/70" style:width={`${card.gpus.percent}%`}></div>
                    </div>
                  {/if}
                </div>
              {/if}
              {#if card.models}
                <p class="relative truncate font-mono text-xs text-muted-foreground">{card.models}</p>
              {/if}
            {/if}

            <p class="relative mt-auto border-t pt-2.5 text-xs text-muted-foreground">
              {workspace.member_count === 1 ? "1 member" : `${workspace.member_count} members`}
            </p>
          </a>
        </li>
      {/each}
      <li>
        <button
          type="button"
          onclick={() => (creating = true)}
          class="flex h-full min-h-44 w-full items-center justify-center gap-2 rounded-xl border border-dashed text-sm
            text-muted-foreground outline-none transition-colors duration-200 ease-out hover:border-foreground/25
            hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          <PlusIcon class="size-4" /> New workspace
        </button>
      </li>
    </ul>
  </div>
</div>

<NewWorkspaceDialog bind:open={creating} />
