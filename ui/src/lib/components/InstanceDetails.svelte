<script lang="ts">
  import { untrack } from "svelte";
  import { fly } from "svelte/transition";
  import { api, type UsagePointRead, type WatchedInstanceRead } from "$lib/api/client";
  import UsageChart from "$lib/components/UsageChart.svelte";
  import { duration, easeOut } from "$lib/motion";
  import { TONE_DOT } from "$lib/servers";
  import {
    formatNumber,
    formatSeconds,
    HISTORY_MINUTES,
    INSTANCE_TONE,
    INSTANCE_WORDS,
    instanceReason,
    instanceSince,
  } from "$lib/watch";

  // The selected instance: what it runs, how long it's been in its state, and its recent usage.
  let { workspaceId, serverId, instance }: { workspaceId: number; serverId: number; instance: WatchedInstanceRead } =
    $props();

  const HISTORY_SECONDS = HISTORY_MINUTES * 60;

  let points = $state.raw<UsagePointRead[]>([]);
  // How many readings the history window holds, from the history's interval.
  let cap = 90;

  const percent = (value: number) => `${formatNumber(value)}%`;
  // Each poll brings a new `instance` object; only a different name means a different selection.
  const name = $derived(instance.name);

  // A new selection loads its history once...
  $effect(() => {
    const selected = name;
    untrack(() => void loadHistory(selected));
  });

  // ...and each poll's newest reading keeps it current.
  $effect(() => {
    const latest = instance.usage;
    if (!latest) return;
    untrack(() => {
      const last = points.at(-1);
      if (!last || Date.parse(latest.at) > Date.parse(last.at)) points = [...points, latest].slice(-cap);
    });
  });

  async function loadHistory(name: string) {
    points = [];
    const { data } = await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/instances/{name}/history", {
      params: { path: { workspace_id: workspaceId, server_id: serverId, name } },
    });
    if (!data || name !== instance.name) return;
    cap = Math.max(1, Math.round(HISTORY_SECONDS / data.interval_seconds));
    // Readings that arrived while the history was on its way are newer: keep them after it.
    const after = Date.parse(data.points.at(-1)?.at ?? "1970-01-01T00:00:00Z");
    points = [...data.points, ...points.filter((each) => Date.parse(each.at) > after)].slice(-cap);
  }
</script>

{#key instance.name}
  <div class="space-y-3" in:fly={{ y: 8, duration: duration(200), easing: easeOut }}>
    <p class="flex items-center gap-1.5 text-sm">
      <span
        class="size-2 shrink-0 rounded-full {TONE_DOT[INSTANCE_TONE[instance.state]]}
               {instance.state === 'starting' ? 'motion-safe:animate-pulse' : ''}"
        aria-hidden="true"
      ></span>
      <span class="font-medium">{INSTANCE_WORDS[instance.state]}</span>
      <span class="text-muted-foreground">· {instanceSince(instance)}</span>
    </p>
    <p class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span class="font-mono font-medium break-all text-foreground">{instance.model ?? "—"}</span>
      <span>image <span class="font-mono break-all">{instance.image}</span></span>
      <span>context <span class="font-mono tabular-nums">{formatNumber(instance.max_model_len)}</span></span>
      <span>{instance.framework === "vllm" ? "vLLM" : instance.framework} <span class="font-mono">{instance.version ?? "—"}</span></span>
    </p>

    {#if instance.state === "ready"}
      <div class="grid gap-x-6 gap-y-5 sm:grid-cols-2">
        <UsageChart
          title="Requests"
          {points}
          value={(p) => p.running}
          second={(p) => p.waiting}
          legend={["running", "waiting"]}
          format={(v) => formatNumber(v)}
        />
        <UsageChart title="KV cache used" {points} value={(p) => p.kv_cache_percent} format={percent} max={100} />
        <UsageChart
          title="Tokens per second"
          {points}
          value={(p) => p.tokens_out_per_s}
          second={(p) => p.tokens_in_per_s}
          legend={["out", "in"]}
          format={(v) => formatNumber(v)}
        />
        <UsageChart title="Time to first token" {points} value={(p) => p.ttft_seconds} format={formatSeconds} />
      </div>
    {:else}
      <p class="rounded-lg border px-4 py-3 text-sm">
        {instanceReason(instance) ?? INSTANCE_WORDS[instance.state]}
      </p>
    {/if}
  </div>
{/key}
