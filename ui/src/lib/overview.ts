/** What a workspace's card on the landing page says, from its overview. */

import type { InstanceState, WorkspaceOverviewRead } from "$lib/api/client";
import type { Tone } from "$lib/servers";
import { gpuMemoryPercent, INSTANCE_TONE, INSTANCE_WORDS, shortModel } from "$lib/watch";

/** How many are in one status, for a card row; `words` names the status, for hover and screen readers. */
export type StatusCount = { tone: Tone; count: number; words: string };
export type GpuLine = { label: string; memory: string | null; percent: number | null };

export type OverviewCard = {
  /** No overview has come back yet. */
  checking: boolean;
  /** No watched servers (or not in the overview yet: created since the last poll). */
  empty: boolean;
  /** Both rows hold one count per tone, in `TONES` order, zeros included, so their columns line up. */
  servers: StatusCount[] | null;
  instances: StatusCount[] | null;
  gpus: GpuLine | null;
  models: string | null;
};

const NO_LINES = { servers: null, instances: null, gpus: null, models: null };
const TONES: readonly Tone[] = ["ok", "warn", "bad", "none"];
const MIB_PER_GIB = 1024;
const MIB_PER_TIB = 1024 * 1024;

export function overviewCard(overview: WorkspaceOverviewRead | undefined, loaded: boolean): OverviewCard {
  if (!overview || overview.servers.total === 0) return { checking: !loaded, empty: loaded, ...NO_LINES };
  return {
    checking: false,
    empty: false,
    servers: serverCounts(overview.servers),
    instances: instanceCounts(overview.instances as Partial<Record<InstanceState, number>>),
    gpus: gpuLine(overview.gpus),
    models: modelsLabel(overview.models),
  };
}

function serverCounts(servers: WorkspaceOverviewRead["servers"]): StatusCount[] {
  const { total, up, trouble, docker_problem } = servers;
  return [
    { tone: "ok", count: up, words: "up" },
    { tone: "warn", count: docker_problem, words: "Docker unusable" },
    { tone: "bad", count: trouble, words: "can't connect" },
    // The rest: never tested, or still being checked.
    { tone: "none", count: total - up - docker_problem - trouble, words: "not tested or checking" },
  ];
}

// Stopped ones aren't counted: they need nothing.
const COUNTED_STATES = (Object.keys(INSTANCE_TONE) as InstanceState[]).filter((state) => state !== "stopped");

function instanceCounts(counts: Partial<Record<InstanceState, number>>): StatusCount[] {
  return TONES.map((tone) => {
    const states = COUNTED_STATES.filter((state) => INSTANCE_TONE[state] === tone);
    return {
      tone,
      count: states.reduce((sum, state) => sum + (counts[state] ?? 0), 0),
      words: states.map((state) => INSTANCE_WORDS[state].toLowerCase()).join(" or "),
    };
  });
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
