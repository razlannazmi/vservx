/** What watching a server shows: card lines, instance words and tones, and the numbers' formats. */

import type {
  DockerStatus,
  GpuRead,
  InstanceSource,
  InstanceState,
  RemovedInstanceRead,
  ServerRead,
  WatchedInstanceRead,
  WatchSummaryRead,
} from "$lib/api/client";
import { clockTime, elapsed, relativeTime } from "$lib/format";
import { serverStatus, type Tone } from "$lib/servers";

/** One line of a server's instance list: a container that's there, or one removed in the last 7 days. */
export type InstanceRow = { removed: false; instance: WatchedInstanceRead } | { removed: true; instance: RemovedInstanceRead };

/** An instance is its source and its name within the server: a system and a --user vllm.service are two. */
export type InstanceRef = { source: InstanceSource; name: string };

const SOURCES: readonly string[] = ["docker", "systemd", "systemd-user"] satisfies InstanceSource[];

export function isInstanceSource(text: string): text is InstanceSource {
  return SOURCES.includes(text);
}

/** "systemd-user:vllm.service": one string per instance, for keys and comparisons. */
export function instanceKey(instance: InstanceRef): string {
  return `${instance.source}:${instance.name}`;
}

/** When a removed container went, as its row and card say it: "7 Nov". */
export function dayMonth(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** The page asks for the cards and the open server this often (the backend reads usage every 5 s). */
export const WATCH_POLL_MS = 5_000;

/** Minutes of usage the charts show; matches the backend's `history_minutes` default. */
export const HISTORY_MINUTES = 30;

/** The state label, and its detail, for this machine in a workspace no app admin owns. */
export const NEEDS_ADMIN_OWNER = "Needs an admin owner";
export const NEEDS_ADMIN_OWNER_DETAIL = "This machine is only watched while an app admin owns this workspace.";

export const INSTANCE_WORDS: Record<InstanceState, string> = {
  ready: "Ready",
  starting: "Starting",
  not_responding: "Not responding",
  restarting: "Restarting",
  crashed: "Crashed",
  stopped: "Stopped",
  paused: "Paused",
  unreachable: "Can't reach",
};

export const INSTANCE_TONE: Record<InstanceState, Tone> = {
  ready: "ok",
  starting: "none",
  not_responding: "bad",
  restarting: "warn",
  crashed: "bad",
  stopped: "none",
  paused: "none",
  unreachable: "warn",
};

// The card line is narrow and truncates, so problems come first, before the total, in this order.
const PROBLEMS: [InstanceState, string][] = [
  ["crashed", "crashed"],
  ["not_responding", "not responding"],
  ["restarting", "restarting"],
  ["unreachable", "can't reach"],
];

// After the total, each only when there's at least one. Stopped ones aren't on the card: they need nothing.
const OTHERS: [InstanceState, string][] = [
  ["starting", "starting"],
  ["paused", "paused"],
];

const DOCKER_PROBLEMS: Partial<Record<DockerStatus, string>> = {
  needs_sudo_password: "needs sudo password",
  sudo_password_rejected: "sudo password rejected",
  sudo_needs_tty: "sudo needs a terminal",
  unavailable: "can't run docker",
};

function times(count: number): string {
  return `${count} ${count === 1 ? "time" : "times"}`;
}

/** The card's dot and line, from watching; jump hosts (and cards before the first poll) keep their latest test. */
export function cardStatus(server: ServerRead, summary: WatchSummaryRead | undefined): { tone: Tone; label: string } {
  if (server.jump_only || !summary || summary.state === "jump_only") return serverStatus(server);
  switch (summary.state) {
    case "not_tested":
      return { tone: "none", label: "not tested yet" };
    case "checking":
      return { tone: "none", label: "checking…" };
    case "host_key_changed":
      return { tone: "warn", label: "host key changed" };
    case "needs_admin_owner":
      return { tone: "warn", label: NEEDS_ADMIN_OWNER };
    case "sign_in_failed":
      return { tone: "bad", label: "sign-in failed" };
    case "unreachable":
      return { tone: "bad", label: summary.since ? `unreachable · since ${clockTime(summary.since)}` : "unreachable" };
  }
  const problem = DOCKER_PROBLEMS[summary.docker];
  if (problem) return { tone: "warn", label: problem };
  // Connected, but the first look for instances hasn't finished.
  if (summary.docker === "unknown") return { tone: "none", label: "checking…" };
  return instanceLine(summary.counts as Partial<Record<InstanceState, number>>) ?? { tone: "ok", label: "no instances" };
}

/** Instance counts as one line, problems first (the line truncates), for server and workspace cards.
 * Null when there are none. */
export function instanceLine(counts: Partial<Record<InstanceState, number>>): { tone: Tone; label: string } | null {
  const count = (state: InstanceState) => counts[state] ?? 0;
  const total = Object.values(counts).reduce<number>((sum, each) => sum + (each ?? 0), 0);
  if (total === 0) return null;
  const listed = (states: [InstanceState, string][]) =>
    states.filter(([state]) => count(state) > 0).map(([state, words]) => `${count(state)} ${words}`);
  const parts = [...listed(PROBLEMS), total === 1 ? "1 instance" : `${total} instances`, ...listed(OTHERS)];
  const tone: Tone =
    count("crashed") + count("not_responding") > 0 ? "bad" : count("restarting") + count("unreachable") > 0 ? "warn" : "ok";
  return { tone, label: parts.join(" · ") };
}

/** How long an instance has been in its state, for its header: "up 3 days", "exited 137 · 2 h ago". */
export function instanceSince(instance: WatchedInstanceRead, now: Date = new Date()): string {
  const { started_at, finished_at } = instance;
  switch (instance.state) {
    case "starting":
      return started_at ? `loading the model · ${elapsed(started_at, now)}` : "loading the model";
    case "crashed":
    case "stopped":
      return `exited ${instance.exit_code ?? "?"}${finished_at ? ` · ${relativeTime(finished_at, now)}` : ""}`;
    case "restarting":
      return `restarted ${times(instance.restart_count)}`;
    case "paused":
      return "paused";
    default:
      // Ready, not responding, can't reach: the container has been up this long.
      return started_at ? `up ${elapsed(started_at, now)}` : "up";
  }
}

/** Why an instance shows no usage, in a sentence or two; null when it's ready. */
export function instanceReason(instance: WatchedInstanceRead, now: Date = new Date()): string | null {
  const ago = instance.finished_at ? ` · ${relativeTime(instance.finished_at, now)}` : "";
  switch (instance.state) {
    case "ready":
      return null;
    case "starting":
      return "The container is up, but vLLM isn't answering /health yet. Usage appears once it's ready.";
    case "not_responding":
      return "vLLM was ready, but isn't answering /health now.";
    case "unreachable":
      return instance.message;
    case "paused":
      return "Paused in Docker.";
    case "restarting":
      return `Docker is restarting it. It has restarted ${times(instance.restart_count)}.`;
    case "stopped":
      return `Stopped · exited with code ${instance.exit_code ?? "?"}${ago}.`;
    case "crashed": {
      let reason = instance.oom_killed
        ? `Killed for running out of memory${ago}.`
        : `Exited with code ${instance.exit_code ?? "?"}${ago}.`;
      if (!instance.oom_killed && instance.exit_code === 137) {
        reason += " Code 137 means the container was killed, often because it ran out of memory.";
      }
      if (instance.restart_count > 0) reason += ` Docker restarted it ${times(instance.restart_count)}.`;
      return reason;
    }
  }
}

/** "Llama-3.1-8B-Instruct" from "meta-llama/Llama-3.1-8B-Instruct". */
export function shortModel(model: string | null): string {
  return model ? (model.split("/").at(-1) ?? model) : "—";
}

/** Long instance lists get a search box and these chips; above this many rows. */
export const INSTANCE_FILTER_FROM = 7;

export type InstanceFilter = "all" | "ready" | "attention" | "stopped";

export const INSTANCE_FILTERS: [InstanceFilter, string][] = [
  ["all", "All"],
  ["ready", "Ready"],
  ["attention", "Needs attention"],
  ["stopped", "Stopped"],
];

/** Whether an instance belongs under a chip; "needs attention" is anything shown amber or red. */
export function matchesFilter(instance: Pick<WatchedInstanceRead, "state">, filter: InstanceFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "ready":
    case "stopped":
      return instance.state === filter;
    case "attention": {
      const tone = INSTANCE_TONE[instance.state];
      return tone === "bad" || tone === "warn";
    }
  }
}

/** Every word of the search appears in the container's name, model, or port. */
export function matchesQuery(instance: Pick<WatchedInstanceRead, "name" | "model" | "port">, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const text = `${instance.name} ${instance.model ?? ""} ${instance.port}`.toLowerCase();
  return words.every((word) => text.includes(word));
}

/** The instances whose state differs from the last poll's; new names and missing ones don't count. */
export function changedStates(
  last: ReadonlyMap<string, InstanceState>,
  instances: Pick<WatchedInstanceRead, "name" | "state">[],
): string[] {
  return instances
    .filter((each) => {
      const before = last.get(each.name);
      return before !== undefined && before !== each.state;
    })
    .map((each) => each.name);
}

/** "all", "0–3", "0, 1, 5", or "—" when Docker didn't say. */
export function gpuLabel(gpus: string[] | null): string {
  if (!gpus || gpus.length === 0) return "—";
  if (gpus.includes("all")) return "all";
  if (!gpus.every((each) => /^\d+$/.test(each))) return gpus.join(", ");
  const ids = [...new Set(gpus.map(Number))].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let start = 0; start < ids.length; ) {
    let end = start;
    while (end + 1 < ids.length && ids[end + 1] === ids[end] + 1) end++;
    // Runs of three or more fold; two stay a list.
    if (end - start >= 2) parts.push(`${ids[start]}–${ids[end]}`);
    else for (let i = start; i <= end; i++) parts.push(String(ids[i]));
    start = end + 1;
  }
  return parts.join(", ");
}

/** How full a GPU's memory is, 0–100; null when nvidia-smi didn't say. */
export function gpuMemoryPercent(gpu: Pick<GpuRead, "memory_used_mib" | "memory_total_mib">): number | null {
  const { memory_used_mib: used, memory_total_mib: total } = gpu;
  if (used === null || total === null || total <= 0) return null;
  return Math.min(Math.max((used / total) * 100, 0), 100);
}

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** "0.42 s". */
export function formatSeconds(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(2)} s`;
}
