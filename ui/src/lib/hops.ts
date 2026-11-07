/**
 * The sign-in page's picture of what vservx does: a jump-host chain lights hop by hop, then the vLLM containers on
 * the last server turn up. The names, ports and states are the README's example, not real servers: nobody is signed
 * in yet, so there is nothing real to show.
 */

import type { InstanceState } from "$lib/api/client";

export const HOPS: readonly { name: string; note: string | null }[] = [
  { name: "you", note: null },
  { name: "bastion-1", note: "host key ok" },
  { name: "bastion-2", note: "host key ok" },
  { name: "gpu-7", note: "host key ok" },
];

export const CONTAINERS: readonly { port: number; state: InstanceState }[] = [
  { port: 8000, state: "ready" },
  { port: 8001, state: "ready" },
  { port: 8002, state: "starting" },
];

// The order things light in: each hop, then the link to the next hop, then the containers one by one.
export const hopStep = (hop: number) => 2 * hop;
export const linkStep = (hop: number) => 2 * hop + 1;
export const containerStep = (container: number) => 2 * HOPS.length - 1 + container;
export const CHAIN_STEPS = 2 * HOPS.length - 1 + CONTAINERS.length;

// Milliseconds from the start of a loop. The chain fades in empty, lights step by step, holds, fades out fully lit,
// and goes dark while still hidden so nothing visibly switches off.
const SHOW_MS = 300;
const STEP_AT: readonly number[] = (() => {
  const at: number[] = [];
  let t = SHOW_MS + 600;
  for (let hop = 0; hop < HOPS.length; hop++) {
    at.push(t);
    if (hop < HOPS.length - 1) {
      at.push((t += 450));
      t += 550;
    }
  }
  t += 750;
  for (let container = 0; container < CONTAINERS.length; container++) {
    at.push(t);
    t += 260;
  }
  return at;
})();
const FADE_MS = STEP_AT[STEP_AT.length - 1] + 3200;
export const CHAIN_LOOP_MS = FADE_MS + 350;

// Every moment the scene changes, in order, ending with the loop starting again.
const CHANGES = [SHOW_MS, ...STEP_AT, FADE_MS, CHAIN_LOOP_MS];

export interface ChainScene {
  /** How many steps have lit: hop `i` is lit when `lit > hopStep(i)`. */
  lit: number;
  shown: boolean;
}

/** The scene `ms` milliseconds after the animation started; it loops forever. */
export function chainScene(ms: number): ChainScene {
  const t = ms % CHAIN_LOOP_MS;
  return { lit: STEP_AT.filter((at) => at <= t).length, shown: t >= SHOW_MS && t < FADE_MS };
}

/** Milliseconds from `ms` until the scene next changes, so a timer can sleep until then. */
export function untilNextChange(ms: number): number {
  const t = ms % CHAIN_LOOP_MS;
  return CHANGES.find((at) => at > t)! - t;
}

/** The finished scene, held still when the system asks for less motion. */
export const STILL_SCENE: ChainScene = { lit: CHAIN_STEPS, shown: true };
