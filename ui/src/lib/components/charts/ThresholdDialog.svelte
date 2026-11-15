<script lang="ts">
  import { untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { api, errorMessage, type InstanceSource, type ThresholdRead } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { THRESHOLD_METRICS } from "$lib/thresholds";

  // Sets where one metric of an instance turns amber and red, for everyone in the workspace.
  // - An empty box means no line at that level.
  // - Reset to default goes back to the metric's default, which differs from both boxes empty for KV cache.
  let {
    open = $bindable(false),
    workspaceId,
    serverId,
    serverName,
    source,
    name,
    current,
    onsaved,
  }: {
    open?: boolean;
    workspaceId: number;
    serverId: number;
    serverName: string;
    source: InstanceSource;
    name: string;
    current: ThresholdRead;
    onsaved: (read: ThresholdRead) => void;
  } = $props();

  const info = $derived(THRESHOLD_METRICS[current.metric]);
  let warning = $state<number | null>(null);
  let critical = $state<number | null>(null);
  let busy = $state(false);

  // Each opening starts from the values in use.
  $effect(() => {
    if (open) {
      untrack(() => {
        warning = current.warning;
        critical = current.critical;
      });
    }
  });

  // An empty or cleared number box gives null or undefined; both mean no line.
  const value = (entered: number | null | undefined) =>
    typeof entered === "number" && Number.isFinite(entered) ? entered : null;
  const fits = (entered: number | null) => entered === null || (entered >= 0 && (info.max === undefined || entered <= info.max));
  const problem = $derived.by(() => {
    const low = value(warning);
    const high = value(critical);
    if (!fits(low) || !fits(high)) return info.max === undefined ? "Values can't be below 0." : `Values go from 0 to ${info.max}.`;
    if (low !== null && high !== null && low >= high) return "Warning must be below critical.";
    return null;
  });

  const where = $derived({
    params: {
      path: { workspace_id: workspaceId, server_id: serverId, name, metric: current.metric },
      query: { source },
    },
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (problem) return;
    busy = true;
    const { data, error } = await api.PUT(
      "/api/workspaces/{workspace_id}/servers/{server_id}/instances/{name}/thresholds/{metric}",
      { ...where, body: { warning: value(warning), critical: value(critical) } },
    );
    busy = false;
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't save thresholds"));
      return;
    }
    onsaved(data);
    open = false;
  }

  async function reset() {
    busy = true;
    const { data, error } = await api.DELETE(
      "/api/workspaces/{workspace_id}/servers/{server_id}/instances/{name}/thresholds/{metric}",
      where,
    );
    busy = false;
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't reset thresholds"));
      return;
    }
    onsaved(data);
    open = false;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-sm">
    <form class="space-y-4" onsubmit={save}>
      <Dialog.Header>
        <Dialog.Title>Thresholds · {info.title}</Dialog.Title>
        <Dialog.Description>For {name} on {serverName}. Everyone in the workspace sees them.</Dialog.Description>
      </Dialog.Header>
      <div class="space-y-3">
        <div class="grid grid-cols-[6rem_1fr_2rem] items-center gap-2">
          <Label for="threshold-warning" class="flex items-center gap-1.5">
            <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span>Warning
          </Label>
          <Input id="threshold-warning" type="number" min="0" max={info.max} step="any" bind:value={warning} />
          <span class="text-sm text-muted-foreground">{info.unit}</span>
          <Label for="threshold-critical" class="flex items-center gap-1.5">
            <span class="size-2 rounded-full bg-status-bad" aria-hidden="true"></span>Critical
          </Label>
          <Input id="threshold-critical" type="number" min="0" max={info.max} step="any" bind:value={critical} />
          <span class="text-sm text-muted-foreground">{info.unit}</span>
        </div>
        <p class="text-xs text-muted-foreground">Above the value counts. Leave a box empty for no line.</p>
        <p class="min-h-4 text-xs text-destructive" aria-live="polite">{problem ?? ""}</p>
      </div>
      <Dialog.Footer class="sm:justify-between">
        <Button type="button" variant="ghost" disabled={busy || current.is_default} onclick={reset}>Reset to default</Button>
        <div class="flex gap-2 max-sm:flex-col-reverse">
          <Button type="button" variant="outline" onclick={() => (open = false)}>Cancel</Button>
          <Button type="submit" disabled={busy || problem !== null}>Save</Button>
        </div>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
