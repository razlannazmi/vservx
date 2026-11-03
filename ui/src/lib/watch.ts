/** What watching a server shows: card lines, instance words and tones, and the numbers' formats. */

import type { DockerStatus, InstanceState, ServerRead, WatchedInstanceRead, WatchSummaryRead } from "$lib/api/client";
import { clockTime, elapsed, relativeTime } from "$lib/format";
import { serverStatus, type Tone } from "$lib/servers";

/** The page asks for the cards and the open server this often (the backend reads usage every 10 s). */
export const WATCH_POLL_MS = 10_000;

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

// The card line's suffixes, in this order, each only when there's at least one.
const SUFFIXES: [InstanceState, string][] = [
  ["crashed", "crashed"],
  ["not_responding", "not responding"],
  ["restarting", "restarting"],
  ["unreachable", "can't reach"],
  ["starting", "starting"],
  ["stopped", "stopped"],
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
    case "sign_in_failed":
      return { tone: "bad", label: "sign-in failed" };
    case "unreachable":
      return { tone: "bad", label: summary.since ? `unreachable · since ${clockTime(summary.since)}` : "unreachable" };
  }
  const problem = DOCKER_PROBLEMS[summary.docker];
  if (problem) return { tone: "warn", label: problem };
  // Connected, but the first look for instances hasn't finished.
  if (summary.docker === "unknown") return { tone: "none", label: "checking…" };

  const counts = summary.counts as Partial<Record<InstanceState, number>>;
  const count = (state: InstanceState) => counts[state] ?? 0;
  const total = Object.values(counts).reduce<number>((sum, each) => sum + (each ?? 0), 0);
  if (total === 0) return { tone: "ok", label: "no instances" };
  const parts = [total === 1 ? "1 instance" : `${total} instances`];
  for (const [state, words] of SUFFIXES) if (count(state) > 0) parts.push(`${count(state)} ${words}`);
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

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** "0.42 s". */
export function formatSeconds(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(2)} s`;
}
