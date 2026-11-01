/** What a server's latest connection test means at a glance, and how vservx reaches it. */

import type { components } from "$lib/api/schema";
import type { ServerRead } from "$lib/api/client";
import { relativeTime } from "$lib/format";

export type Tone = "ok" | "bad" | "warn" | "none";
export type ConnectionFailure = components["schemas"]["ConnectionFailure"];

const FAILURE_WORDS: Record<ConnectionFailure, string> = {
  unreachable: "unreachable",
  timeout: "timed out",
  auth_failed: "sign-in failed",
  host_key_changed: "host key changed",
  credentials_unreadable: "credentials unreadable",
  error: "error",
};

// Whole class names, so Tailwind finds them.
export const TONE_DOT: Record<Tone, string> = {
  ok: "bg-status-ok",
  bad: "bg-status-bad",
  warn: "bg-status-warn",
  none: "bg-status-none",
};

export function failureWords(failure: ConnectionFailure | null | undefined): string {
  return failure ? FAILURE_WORDS[failure] : "failed";
}

/** A changed host key needs someone to look (amber); any other failure is red. */
export function failureTone(failure: ConnectionFailure | null | undefined): Tone {
  return failure === "host_key_changed" ? "warn" : "bad";
}

/** The card's dot and line. */
export function serverStatus(server: ServerRead, now: Date = new Date()): { tone: Tone; label: string } {
  const test = server.last_test;
  if (!test) return { tone: "none", label: "never tested" };
  if (test.ok) return { tone: "ok", label: `OK · tested ${relativeTime(test.at, now)}` };
  if (test.failure === "host_key_changed") return { tone: "warn", label: "host key changed" };
  return { tone: "bad", label: `${failureWords(test.failure)} · ${relativeTime(test.at, now)}` };
}

/** Names from vservx to the server: "vservx", the outermost jump host first, the server last. */
export function routeOf(server: ServerRead, all: ServerRead[]): string[] {
  const byId = new Map(all.map((each) => [each.id, each]));
  const hops = [server.name];
  const seen = new Set([server.id]);
  let jump = server.jump_server_id;
  // The backend refuses loops; the seen set only keeps a bad list from hanging the page.
  while (jump !== null && !seen.has(jump)) {
    const next = byId.get(jump);
    if (!next) break;
    hops.unshift(next.name);
    seen.add(next.id);
    jump = next.jump_server_id;
  }
  return ["vservx", ...hops];
}
