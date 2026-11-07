<script lang="ts">
  import { toast } from "svelte-sonner";
  import type { SnapshotCompareRead, SnapshotDetailRead } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button/index.js";
  import { localDateTime } from "$lib/format";
  import { copyText, describeDifference, lineDiff } from "$lib/snapshots";

  // Two snapshots side by side: what differs, and both commands as a line diff. Swap only flips
  // what's shown; "older" and "newer" always mean when each happened.
  let { comparison, onswap }: { comparison: SnapshotCompareRead; onswap: () => void } = $props();

  const from = $derived(comparison.from_snapshot);
  const to = $derived(comparison.to_snapshot);
  const twoContainers = $derived(from.instance !== to.instance);
  const configDifferences = $derived(comparison.differences.filter((each) => each.label !== "container"));
  const containerDifference = $derived(comparison.differences.find((each) => each.label === "container") ?? null);
  const lines = $derived(lineDiff(from.command ?? "", to.command ?? ""));

  function isOlder(a: SnapshotDetailRead, b: SnapshotDetailRead): boolean {
    const at = new Date(a.happened_at).getTime() - new Date(b.happened_at).getTime();
    return at < 0 || (at === 0 && a.id < b.id);
  }
  const older = $derived(isOlder(from, to) ? from : to);
  const newer = $derived(older === from ? to : from);

  function label(snapshot: SnapshotDetailRead): string {
    const at = localDateTime(snapshot.happened_at);
    return twoContainers ? `${snapshot.instance} ${at}` : at;
  }

  async function copy(text: string | null) {
    if (await copyText(text ?? "")) toast.success("Copied");
    else toast.error("Couldn't copy. Select the command and copy it.");
  }

  const MARK = { same: "  ", add: "+ ", del: "- " } as const;
  const TONE = { same: "", add: "text-status-ok", del: "text-status-bad" } as const;
</script>

<div class="space-y-3">
  <p class="text-sm font-medium">Comparing {label(from)} → {label(to)}</p>
  {#if configDifferences.length}
    <ul class="space-y-0.5 font-mono text-xs break-all text-muted-foreground">
      {#each configDifferences as difference, i (i)}
        <li>{describeDifference(difference)}</li>
      {/each}
    </ul>
  {:else}
    <p class="text-xs text-muted-foreground">No differences in launch config</p>
  {/if}
  {#if containerDifference}
    <p class="font-mono text-xs text-muted-foreground">{describeDifference(containerDifference)}</p>
  {/if}
  <pre class="max-h-80 overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-5">{#each lines as line, i (i)}<span class="block {TONE[line.kind]}">{MARK[line.kind]}{line.text}</span>{/each}</pre>
  <div class="flex flex-wrap gap-2">
    <Button size="xs" variant="outline" onclick={() => copy(older.command)}>Copy older</Button>
    <Button size="xs" variant="outline" onclick={() => copy(newer.command)}>Copy newer</Button>
    <Button size="xs" variant="outline" onclick={onswap}>Swap</Button>
  </div>
</div>
