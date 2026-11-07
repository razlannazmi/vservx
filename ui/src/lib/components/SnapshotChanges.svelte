<script lang="ts">
  import type { SnapshotEntryRead } from "$lib/api/client";
  import { localDateTime } from "$lib/format";
  import { differenceChange, KIND_WORDS } from "$lib/snapshots";

  // A change list, newest first. In pick mode each entry gets a checkbox; removed entries have no
  // config of their own, so they can't be picked.
  let {
    entries,
    showInstance,
    picking,
    picks,
    onpick,
    onopen,
    onmore,
  }: {
    entries: SnapshotEntryRead[];
    showInstance: boolean;
    picking: boolean;
    picks: number[];
    onpick: (id: number) => void;
    onopen: (entry: SnapshotEntryRead) => void;
    onmore: (() => void) | null;
  } = $props();

  // Shown beside when it happened only when vservx saw it more than one discovery later.
  function noticedLate(entry: SnapshotEntryRead): boolean {
    return Math.abs(new Date(entry.noticed_at).getTime() - new Date(entry.happened_at).getTime()) > 60_000;
  }

  // The muted line under the first: when vservx noticed it late, and when a removed one was last seen.
  function times(entry: SnapshotEntryRead): string[] {
    const parts: string[] = [];
    if (noticedLate(entry)) parts.push(`noticed ${localDateTime(entry.noticed_at)}`);
    if (entry.kind === "removed" && entry.last_seen) parts.push(`last seen ${localDateTime(entry.last_seen)}`);
    return parts;
  }
</script>

{#if entries.length === 0}
  <p class="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
    No snapshots yet. vservx takes one the first time it sees each container.
  </p>
{:else}
  <ol class="divide-y rounded-lg border text-xs">
    {#each entries as entry (entry.id)}
      {@const removed = entry.kind === "removed"}
      {@const when = times(entry)}
      <li class="flex gap-3 px-3 py-3">
        {#if picking}
          <input
            type="checkbox"
            class="mt-1 size-3.5 shrink-0 accent-foreground"
            checked={picks.includes(entry.id)}
            disabled={removed}
            aria-label={`Pick the snapshot of ${localDateTime(entry.happened_at)}`}
            onchange={() => onpick(entry.id)}
          />
        {/if}
        <div class="min-w-0 flex-1 space-y-2">
          <!-- The container (all on server) or what happened (one instance) leads; when it happened
               sits right, so dates line up down the list. Then what happened (all on server), then
               when vservx noticed, each on its own line. -->
          <div class="space-y-0.5">
            <div class="flex items-baseline justify-between gap-3">
              <p class="min-w-0 truncate text-sm font-medium {removed ? 'text-muted-foreground' : ''}">
                {#if showInstance}
                  <span class="font-mono">{entry.instance}</span>
                {:else}
                  {KIND_WORDS[entry.kind]}
                {/if}
              </p>
              <time datetime={entry.happened_at} class="shrink-0 tabular-nums text-muted-foreground">
                {localDateTime(entry.happened_at)}
              </time>
            </div>
            {#if showInstance && entry.model}
              <p class="truncate font-mono text-muted-foreground" title={entry.model}>{entry.model}</p>
            {/if}
            {#if showInstance}
              <p>{KIND_WORDS[entry.kind]}</p>
            {/if}
            {#if when.length}
              <p class="text-muted-foreground">{when.join(" · ")}</p>
            {/if}
          </div>
          {#if entry.differences.length}
            <!-- Setting on the left, what happened to it on the right. -->
            <dl class="grid grid-cols-[fit-content(45%)_minmax(0,1fr)] gap-x-3 gap-y-1 font-mono leading-5">
              {#each entry.differences as difference, i (i)}
                <dt class="break-all text-muted-foreground">{difference.label}</dt>
                <dd class="break-all">{differenceChange(difference)}</dd>
              {/each}
            </dl>
          {/if}
          <div class="flex items-center justify-between gap-3 text-muted-foreground">
            <span class="font-mono">{entry.container_id ?? ""}</span>
            {#if !removed}
              <button
                type="button"
                class="rounded-sm underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                onclick={() => onopen(entry)}
              >
                View command
              </button>
            {/if}
          </div>
        </div>
      </li>
    {/each}
  </ol>
  {#if onmore}
    <button
      type="button"
      class="rounded-sm text-xs text-muted-foreground underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      onclick={onmore}
    >
      Show older
    </button>
  {/if}
{/if}
