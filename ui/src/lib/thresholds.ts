/** Instance thresholds in the UI: how each metric is named and measured, and loading an instance's. */

import { api, type InstanceSource, type ThresholdMetric, type ThresholdRead } from "$lib/api/client";

/** KV cache is a share of the cache, so its thresholds stop at 100. */
export const THRESHOLD_METRICS: Record<ThresholdMetric, { title: string; unit: string; max?: number }> = {
  waiting: { title: "Waiting requests", unit: "req" },
  kv_cache_percent: { title: "KV cache used", unit: "%", max: 100 },
  ttft_seconds: { title: "Time to first token", unit: "s" },
};

/** Every metric's thresholds for the instance, or null when they couldn't be read. */
export async function loadThresholds(
  workspaceId: number,
  serverId: number,
  source: InstanceSource,
  name: string,
): Promise<ThresholdRead[] | null> {
  const { data } = await api.GET("/api/workspaces/{workspace_id}/servers/{server_id}/instances/{name}/thresholds", {
    params: { path: { workspace_id: workspaceId, server_id: serverId, name }, query: { source } },
  });
  return data?.thresholds ?? null;
}
