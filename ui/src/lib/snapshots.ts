/** Launch snapshots in the web app: the drawer's state in the address, the "changed" tag, the
 * line diff of two commands, and copying without the clipboard API (plain-http deployments). */

import type { DifferenceRead, SnapshotKind } from "$lib/api/client";
import { clockTime } from "$lib/format";

export type DrawerState = {
  view: "server" | "instance";
  // The instance "This instance" shows; null falls back to the one selected on the page.
  instance: string | null;
  // An older snapshot shown in place of the current one.
  at: number | null;
  compare: [number, number] | null;
};

// "server", or "instance/<name>". Docker container names never hold "/", so a container named
// "server" can't collide with the server view.
const KEY = "snapshots";
const INSTANCE = "instance/";

function whole(text: string | null): number | null {
  return text !== null && /^\d+$/.test(text) ? Number(text) : null;
}

export function readDrawer(search: string): DrawerState | null {
  const params = new URLSearchParams(search);
  const value = params.get(KEY);
  let view: DrawerState["view"];
  let instance: string | null = null;
  if (value === "server") view = "server";
  else if (value?.startsWith(INSTANCE) && value.length > INSTANCE.length) {
    view = "instance";
    instance = value.slice(INSTANCE.length);
  } else return null;
  const pair = (params.get("compare") ?? "").split(",").map(whole);
  const compare: [number, number] | null =
    pair.length === 2 && pair[0] !== null && pair[1] !== null ? [pair[0], pair[1]] : null;
  return { view, instance, at: whole(params.get("at")), compare };
}

/** The query string for a drawer state, "" when it's closed. The server view leaves its
 * instance out: it's the page's selected instance, already in the path. */
export function drawerSearch(state: DrawerState | null): string {
  if (state === null) return "";
  const view = state.view === "instance" && state.instance ? INSTANCE + encodeURIComponent(state.instance) : "server";
  let search = `?${KEY}=${view}`;
  if (state.at !== null) search += `&at=${state.at}`;
  if (state.compare !== null) search += `&compare=${state.compare[0]},${state.compare[1]}`;
  return search;
}

export const CHANGED_WINDOW_MS = 24 * 60 * 60 * 1000;

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** "changed 14:32", "changed yesterday 22:10", or null outside the last 24 hours. */
export function changedLabel(changedAt: string | null, now: Date = new Date()): string | null {
  if (changedAt === null) return null;
  const at = new Date(changedAt);
  if (now.getTime() - at.getTime() > CHANGED_WINDOW_MS) return null;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  return sameDay(at, yesterday) ? `changed yesterday ${clockTime(changedAt)}` : `changed ${clockTime(changedAt)}`;
}

export const KIND_WORDS: Record<SnapshotKind, string> = {
  first_seen: "first seen",
  recreated: "recreated",
  recreated_same: "recreated, same config",
  changed: "changed",
  removed: "removed",
};

/** What happened to one setting, without its label: "8192 → 16384", "added <HF_TOKEN>", "removed",
 * or the note ("re-pulled", "can't compare (…)"). */
export function differenceChange(d: DifferenceRead): string {
  if (d.note) return d.note;
  if (d.before === null) return d.after ? `added ${d.after}` : "added";
  if (d.after === null) return "removed";
  return `${d.before} → ${d.after}`;
}

/** One difference in words: "--max-model-len 8192 → 16384", "-e HF_TOKEN added <HF_TOKEN>",
 * "image re-pulled", "API key: can't compare (…)". */
export function describeDifference(d: DifferenceRead): string {
  const separator = d.note && d.before === null && d.after === null ? ": " : " ";
  return `${d.label}${separator}${differenceChange(d)}`;
}

export type DiffLine = { kind: "same" | "add" | "del"; text: string };

/** Two texts line by line (longest common subsequence), removed lines before added ones. */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  // common[i][j]: the longest common run of a[i:] and b[j:].
  const common = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      common[i][j] = a[i] === b[j] ? common[i + 1][j + 1] + 1 : Math.max(common[i + 1][j], common[i][j + 1]);
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      lines.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (common[i + 1][j] >= common[i][j + 1]) lines.push({ kind: "del", text: a[i++] });
    else lines.push({ kind: "add", text: b[j++] });
  }
  while (i < a.length) lines.push({ kind: "del", text: a[i++] });
  while (j < b.length) lines.push({ kind: "add", text: b[j++] });
  return lines;
}

/** Copy through a hidden textarea, for when the clipboard API is missing (plain http). */
function textareaCopy(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand("copy");
  } finally {
    area.remove();
  }
}

/** Whether the text was copied: the clipboard API first, then the fallback. */
export async function copyText(
  text: string,
  clipboard: Pick<Clipboard, "writeText"> | undefined = globalThis.navigator?.clipboard,
  fallback: (text: string) => boolean = textareaCopy,
): Promise<boolean> {
  if (clipboard) {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // Denied, or not allowed here: try the fallback.
    }
  }
  try {
    return fallback(text);
  } catch {
    return false;
  }
}
