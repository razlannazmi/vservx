/** What a workspace's card on the landing page says, from its overview. */

import type { InstanceState, WorkspaceOverviewRead } from "$lib/api/client";
import type { Tone } from "$lib/servers";
import { gpuMemoryPercent, instanceLine, shortModel } from "$lib/watch";

export type CardLine = { tone: Tone; label: string };
export type GpuLine = { label: string; memory: string | null; percent: number | null };

export type OverviewCard = {
  /** No overview has come back yet. */
  checking: boolean;
  /** No watched servers (or not in the overview yet: created since the last poll). */
  empty: boolean;
  servers: CardLine | null;
  instances: CardLine | null;
  gpus: GpuLine | null;
  models: string | null;
};

const NO_LINES = { servers: null, instances: null, gpus: null, models: null };
const MIB_PER_GIB = 1024;
const MIB_PER_TIB = 1024 * 1024;

export function overviewCard(overview: WorkspaceOverviewRead | undefined, loaded: boolean): OverviewCard {
  if (!overview || overview.servers.total === 0) return { checking: !loaded, empty: loaded, ...NO_LINES };
  return {
    checking: false,
    empty: false,
    servers: serversLine(overview.servers),
    instances: instanceLine(overview.instances as Partial<Record<InstanceState, number>>),
    gpus: gpuLine(overview.gpus),
    models: modelsLabel(overview.models),
  };
}

function serversLine(servers: WorkspaceOverviewRead["servers"]): CardLine {
  const { total, up, not_tested, unreachable, trouble, docker_problem } = servers;
  const attention = trouble + docker_problem;
  if (attention > 0) {
    const label = attention === unreachable ? `${unreachable} of ${total} unreachable` : `${attention} of ${total} need attention`;
    return { tone: trouble > 0 ? "bad" : "warn", label };
  }
  if (up === total) return { tone: "ok", label: total === 1 ? "1 server up" : `${total} servers up` };
  if (up > 0) return { tone: "ok", label: `${up} of ${total} servers up` };
  // Never-tested servers aren't watched, so "checking…" would never end for them.
  return not_tested === total ? { tone: "none", label: "not tested yet" } : { tone: "none", label: "checking…" };
}

function gpuLine(gpus: WorkspaceOverviewRead["gpus"]): GpuLine | null {
  if (!gpus) return null;
  const label = gpus.count === 1 ? "1 GPU" : `${gpus.count} GPUs`;
  const { memory_used_mib: used, memory_total_mib: total } = gpus;
  if (used === null || total === null) return { label, memory: null, percent: null };
  return { label, memory: memoryLabel(used, total), percent: gpuMemoryPercent(gpus) };
}

/** "212 / 384 GiB", or "1.6 / 1.9 TiB" from 1 TiB of total up; the total picks the unit for both. */
export function memoryLabel(usedMib: number, totalMib: number): string {
  if (totalMib < MIB_PER_TIB) return `${Math.round(usedMib / MIB_PER_GIB)} / ${Math.round(totalMib / MIB_PER_GIB)} GiB`;
  return `${(usedMib / MIB_PER_TIB).toFixed(1)} / ${(totalMib / MIB_PER_TIB).toFixed(1)} TiB`;
}

/** The first two models, short, then how many more. */
function modelsLabel(models: string[]): string | null {
  if (models.length === 0) return null;
  const shown = models.slice(0, 2).map(shortModel);
  return (models.length > 2 ? [...shown, `+${models.length - 2}`] : shown).join(" · ");
}
