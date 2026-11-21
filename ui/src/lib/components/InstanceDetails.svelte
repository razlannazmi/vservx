<script lang="ts">
  import { untrack } from "svelte";
  import { fly } from "svelte/transition";
  import { api, type ThresholdMetric, type ThresholdRead, type UsagePointRead, type WatchedInstanceRead } from "$lib/api/client";
  import { missedReadings, shortNumber, thresholdState, type SeriesColor, type SeriesSpec } from "$lib/chart";
  import type { Dashboard } from "$lib/charts/dashboard.svelte";
  import PanelGrid from "$lib/components/charts/PanelGrid.svelte";
  import StatPanel from "$lib/components/charts/StatPanel.svelte";
  import ThresholdDialog from "$lib/components/charts/ThresholdDialog.svelte";
  import TimeSeriesPanel from "$lib/components/charts/TimeSeriesPanel.svelte";
  import { loadThresholds } from "$lib/thresholds";
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
  // and four panels over the dashboard's range, with its thresholds.
  // - Operators and the owner can set thresholds from a panel's menu; everyone sees them.
  let {
    workspaceId,
    serverId,
    serverName,
    instance,
    operator,
    dashboard,
  }: {
    workspaceId: number;
    serverId: number;
    serverName: string;
    instance: WatchedInstanceRead;
    operator: boolean;
    dashboard: Dashboard;
  } = $props();

  let points = $state.raw<UsagePointRead[]>([]);
  // Empty until they load, or when they can't be read: then nothing is drawn and no tile changes colour.
  let thresholds = $state.raw<ThresholdRead[]>([]);
  let editing = $state<ThresholdMetric | null>(null);
  let dialogOpen = $state(false);
  // How many readings the history window holds, and how often the backend takes one, from the history response.
  let cap = 360;
  let intervalSeconds = 5;

  const whole = (value: number) => formatNumber(value);
  const percent = (value: number) => `${formatNumber(value)}%`;
  // Splits between whole requests get no label: half a request means nothing.
  const requestTick = (value: number) => (Number.isInteger(value) ? `${formatNumber(value)} req` : "");

  const REQUESTS: SeriesSpec[] = [
    { key: "running", label: "running", color: 1, value: (point) => point.running },
    { key: "waiting", label: "waiting", color: 3, value: (point) => point.waiting, metric: "waiting" },
  ];
  const KV_CACHE: SeriesSpec[] = [
    { key: "kv", label: "used", color: 4, value: (point) => point.kv_cache_percent, metric: "kv_cache_percent" },
  ];
  const TOKENS: SeriesSpec[] = [
    { key: "out", label: "out", color: 2, value: (point) => point.tokens_out_per_s },
    { key: "in", label: "in", color: 1, value: (point) => point.tokens_in_per_s },
  ];
  const TTFT: SeriesSpec[] = [
    { key: "ttft", label: "mean", color: 3, value: (point) => point.ttft_seconds, metric: "ttft_seconds" },
  ];

  const limits = (metric: ThresholdMetric) => thresholds.find((each) => each.metric === metric) ?? null;
  // Only those who may change thresholds get the menu item, and only once there are values to start from.
  const editor = (metric: ThresholdMetric) =>
    operator && limits(metric)
      ? () => {
          editing = metric;
          dialogOpen = true;
        }
      : undefined;
  const editingRead = $derived(editing ? limits(editing) : null);

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
      metric?: ThresholdMetric,
    ) => {
      const value = usage ? pick(usage) : null;
      const limit = metric ? limits(metric) : null;
      const state = limit ? thresholdState(value, limit.warning, limit.critical) : "ok";
      return { label, value, unit, format, color, state, trend: recent.map(pick) };
    };
    return [
      tile("Running", (point) => point.running, "", whole, 1),
      tile("Waiting", (point) => point.waiting, "", whole, 3, "waiting"),
      tile("KV cache", (point) => point.kv_cache_percent, "%", whole, 4, "kv_cache_percent"),
      tile("Tokens out", (point) => point.tokens_out_per_s, "tok/s", whole, 2),
      tile("TTFT", (point) => point.ttft_seconds, "s", (value) => value.toFixed(2), 3, "ttft_seconds"),
    ];
  });

  // The selection whose thresholds are loaded or on their way; null means ask again.
  let limitsFor: string | null = null;

  // A new selection starts from its history and drops the last one's thresholds...
  $effect(() => {
    const selected = key;
    untrack(() => {
      points = [];
      void loadHistory(selected);
      thresholds = [];
      limitsFor = null;
    });
  });

  // ...and each poll asks for thresholds until they arrive: an instance vservx hasn't recorded yet has none.
  $effect(() => {
    void instance;
    untrack(() => {
      if (limitsFor !== key) void loadLimits(key);
    });
  });

  // ...and each poll's newest reading keeps it current.
  // - A reading well after the last one means the page missed some, as polls stop while the tab is
  //   hidden: the history is fetched again for them, so the line doesn't jump straight across the gap.
  $effect(() => {
    const latest = instance.usage;
    if (!latest) return;
    untrack(() => {
      const last = points.at(-1);
      if (last && Date.parse(latest.at) <= Date.parse(last.at)) return;
      points = [...points, latest].slice(-cap);
      if (last && missedReadings(last.at, latest.at, intervalSeconds)) void loadHistory(key);
    });
  });

  // The panels' live window ends at the newest reading.
  $effect(() => {
    const last = points.at(-1);
    dashboard.end = last ? Date.parse(last.at) : Date.now();
  });

  async function loadHistory(selected: string) {
    const { data } = await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/instances/{name}/history", {
      params: { path: { workspace_id: workspaceId, server_id: serverId, name: instance.name }, query: { source: instance.source } },
    });
    if (!data || selected !== key) return;
    cap = Math.max(1, Math.round((data.history_minutes * 60) / data.interval_seconds));
    intervalSeconds = data.interval_seconds;
    dashboard.historyMinutes = data.history_minutes;
    // Readings that arrived while the history was on its way are newer: keep them after it.
    const after = Date.parse(data.points.at(-1)?.at ?? "1970-01-01T00:00:00Z");
    points = [...data.points, ...points.filter((each) => Date.parse(each.at) > after)].slice(-cap);
  }

  async function loadLimits(selected: string) {
    limitsFor = selected;
    const loaded = await loadThresholds(workspaceId, serverId, instance.source, instance.name);
    if (selected !== key) return;
    if (loaded) thresholds = loaded;
    else limitsFor = null;
  }

  function saved(read: ThresholdRead) {
    thresholds = thresholds.map((each) => (each.metric === read.metric ? read : each));
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
        <TimeSeriesPanel
          title="Requests"
          unit="req"
          {points}
          series={REQUESTS}
          format={whole}
          tick={requestTick}
          threshold={limits("waiting")}
          onthresholds={editor("waiting")}
          {dashboard}
        />
        <TimeSeriesPanel
          title="KV cache used"
          unit="%"
          {points}
          series={KV_CACHE}
          format={percent}
          max={100}
          threshold={limits("kv_cache_percent")}
          onthresholds={editor("kv_cache_percent")}
          {dashboard}
        />
        <TimeSeriesPanel
          title="Tokens per second"
          unit="tok/s"
          {points}
          series={TOKENS}
          format={whole}
          tick={(value) => `${shortNumber(value)} tok/s`}
          {dashboard}
        />
        <TimeSeriesPanel
          title="Time to first token"
          unit="s"
          {points}
          series={TTFT}
          format={formatSeconds}
          threshold={limits("ttft_seconds")}
          onthresholds={editor("ttft_seconds")}
          {dashboard}
        />
      </PanelGrid>
    {:else}
      <p class="rounded-lg border px-4 py-3 text-sm">
        {instanceReason(instance) ?? INSTANCE_WORDS[instance.state]}
      </p>
    {/if}
    <!-- Outside the ready check: an instance that stops answering mid-edit keeps the dialog and what was typed. -->
    {#if editingRead}
      <ThresholdDialog
        bind:open={dialogOpen}
        {workspaceId}
        {serverId}
        {serverName}
        source={instance.source}
        name={instance.name}
        current={editingRead}
        onsaved={saved}
      />
    {/if}
  </div>
{/key}
