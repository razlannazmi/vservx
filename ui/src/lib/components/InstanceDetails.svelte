<script lang="ts">
  import { untrack } from "svelte";
  import { fly } from "svelte/transition";
  import { api, type UsagePointRead, type WatchedInstanceRead } from "$lib/api/client";
  import type { SeriesColor, SeriesSpec } from "$lib/chart";
  import type { Dashboard } from "$lib/charts/dashboard.svelte";
  import PanelGrid from "$lib/components/charts/PanelGrid.svelte";
  import StatPanel from "$lib/components/charts/StatPanel.svelte";
  import TimeSeriesPanel from "$lib/components/charts/TimeSeriesPanel.svelte";
  import { duration, easeOut } from "$lib/motion";
  import { instanceOrigin, TONE_DOT } from "$lib/servers";
  import {
    formatNumber,
    formatSeconds,
    INSTANCE_TONE,
    INSTANCE_WORDS,
    instanceKey,
    instanceReason,
    instanceSince,
  } from "$lib/watch";

  // The selected instance: what it runs, how long it's been in its state, and its usage as a stat row
  // and four panels over the dashboard's range.
  let {
    workspaceId,
    serverId,
    instance,
    dashboard,
  }: { workspaceId: number; serverId: number; instance: WatchedInstanceRead; dashboard: Dashboard } = $props();

  let points = $state.raw<UsagePointRead[]>([]);
  // How many readings the history window holds, from the history's window and interval.
  let cap = 360;

  const whole = (value: number) => formatNumber(value);
  const percent = (value: number) => `${formatNumber(value)}%`;
  const thousands = (value: number) =>
    Math.abs(value) >= 1000 ? `${formatNumber(value / 1000, Math.abs(value) >= 10_000 ? 0 : 1)}k` : formatNumber(value);
  // Splits between whole requests get no label: half a request means nothing.
  const requestTick = (value: number) => (Number.isInteger(value) ? `${formatNumber(value)} req` : "");

  const REQUESTS: SeriesSpec[] = [
    { key: "running", label: "running", color: 1, value: (point) => point.running },
    { key: "waiting", label: "waiting", color: 3, value: (point) => point.waiting },
  ];
  const KV_CACHE: SeriesSpec[] = [{ key: "kv", label: "used", color: 4, value: (point) => point.kv_cache_percent }];
  const TOKENS: SeriesSpec[] = [
    { key: "out", label: "out", color: 2, value: (point) => point.tokens_out_per_s },
    { key: "in", label: "in", color: 1, value: (point) => point.tokens_in_per_s },
  ];
  const TTFT: SeriesSpec[] = [{ key: "ttft", label: "mean", color: 3, value: (point) => point.ttft_seconds }];

  // Each poll brings a new `instance` object; only a different source or name means a different selection.
  const key = $derived(instanceKey(instance));

  // The tiles' trends cover the range up to the newest reading, whatever span the panels are fixed on.
  const recent = $derived(points.filter((point) => Date.parse(point.at) >= dashboard.end - dashboard.range * 60_000));
  const tiles = $derived.by(() => {
    const usage = instance.usage;
    const tile = (
      label: string,
      pick: (point: UsagePointRead) => number | null,
      unit: string,
      format: (value: number) => string,
      color: SeriesColor,
    ) => ({ label, value: usage ? pick(usage) : null, unit, format, color, trend: recent.map(pick) });
    return [
      tile("Running", (point) => point.running, "", whole, 1),
      tile("Waiting", (point) => point.waiting, "", whole, 3),
      tile("KV cache", (point) => point.kv_cache_percent, "%", whole, 4),
      tile("Tokens out", (point) => point.tokens_out_per_s, "tok/s", whole, 2),
      tile("TTFT", (point) => point.ttft_seconds, "s", (value) => value.toFixed(2), 3),
    ];
  });

  // A new selection loads its history once...
  $effect(() => {
    const selected = key;
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

  // The panels' live window ends at the newest reading.
  $effect(() => {
    const last = points.at(-1);
    dashboard.end = last ? Date.parse(last.at) : Date.now();
  });

  async function loadHistory(selected: string) {
    points = [];
    const { data } = await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/instances/{name}/history", {
      params: { path: { workspace_id: workspaceId, server_id: serverId, name: instance.name }, query: { source: instance.source } },
    });
    if (!data || selected !== key) return;
    cap = Math.max(1, Math.round((data.history_minutes * 60) / data.interval_seconds));
    dashboard.historyMinutes = data.history_minutes;
    // Readings that arrived while the history was on its way are newer: keep them after it.
    const after = Date.parse(data.points.at(-1)?.at ?? "1970-01-01T00:00:00Z");
    points = [...data.points, ...points.filter((each) => Date.parse(each.at) > after)].slice(-cap);
  }
</script>

{#key key}
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
      {#if instance.source === "docker"}
        <span>image <span class="font-mono break-all">{instance.image}</span></span>
      {:else}
        <span class="font-mono break-all">{instanceOrigin(instance)}</span>
      {/if}
      <span>context <span class="font-mono tabular-nums">{formatNumber(instance.max_model_len)}</span></span>
      <span>{instance.framework === "vllm" ? "vLLM" : instance.framework} <span class="font-mono">{instance.version ?? "—"}</span></span>
    </p>

    {#if instance.state === "ready"}
      <!-- Five across once there's room, otherwise three then two. -->
      <div class="@container">
        <div class="grid grid-cols-3 gap-1.5 @min-[36rem]:grid-cols-5 @min-[36rem]:gap-2">
          {#each tiles as tile (tile.label)}
            <StatPanel {...tile} />
          {/each}
        </div>
      </div>
      <PanelGrid>
        <TimeSeriesPanel title="Requests" unit="req" {points} series={REQUESTS} format={whole} tick={requestTick} {dashboard} />
        <TimeSeriesPanel title="KV cache used" unit="%" {points} series={KV_CACHE} format={percent} max={100} {dashboard} />
        <TimeSeriesPanel
          title="Tokens per second"
          unit="tok/s"
          {points}
          series={TOKENS}
          format={whole}
          tick={(value) => `${thousands(value)} tok/s`}
          {dashboard}
        />
        <TimeSeriesPanel title="Time to first token" unit="s" {points} series={TTFT} format={formatSeconds} {dashboard} />
      </PanelGrid>
    {:else}
      <p class="rounded-lg border px-4 py-3 text-sm">
        {instanceReason(instance) ?? INSTANCE_WORDS[instance.state]}
      </p>
    {/if}
  </div>
{/key}
